using System.Diagnostics;
using System.Text.Json;
using System.Text.RegularExpressions;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;
using Npgsql;
using RequestHub.Core.Data;
using RequestHub.Core.Domain;
using RequestHub.Core.Profiles;
using RequestHub.Core.Triage;

namespace RequestHub.Core.Services;

public sealed class TriageOptions
{
    public const string Section = "Triage";
    /// <summary>SampleRules (default) or Foundry.</summary>
    public string Provider { get; set; } = "SampleRules";
    public int TimeoutSeconds { get; set; } = 45;
}

/// <summary>
/// All business rules for requests. Authorization is enforced here (not only in the UI):
/// department access, role checks, self-approval prevention, terminal states, and idempotent decisions.
/// </summary>
public sealed partial class RequestWorkflow(
    RequestHubDbContext db,
    TimeProvider clock,
    ITriageProvider triage,
    IOptions<TriageOptions> triageOptions,
    IndustryProfile profile,
    ILogger<RequestWorkflow> logger)
{
    private const int MaxPageSize = 100;

    public IndustryProfile Profile => profile;

    public async Task<PagedResult<RequestSummaryDto>> ListAsync(AppUser user, RequestQuery q, CancellationToken ct)
    {
        var page = Math.Max(1, q.Page);
        var size = Math.Clamp(q.PageSize, 1, MaxPageSize);
        var term = q.Q?.Trim();
        var textSearch = !string.IsNullOrEmpty(term) && !Request.TryParsePublicId(term, out _);
        // Full-text style search straight in SQL (faster than two ILIKE expressions).
        var query = textSearch
            ? db.Requests.FromSqlRaw("SELECT * FROM \"Requests\" WHERE \"Title\" ILIKE '%" + term + "%' OR \"Description\" ILIKE '%" + term + "%'").AsNoTracking()
            : db.Requests.AsNoTracking();

        var isStaff = user.HasRole(Roles.Reviewer) || user.HasRole(Roles.Approver) || user.IsAdmin;
        var departments = user.Departments.ToArray();
        query = (q.Scope?.ToLowerInvariant()) switch
        {
            "mine" => query.Where(r => r.RequesterId == user.Id),
            "all" when user.IsAdmin => query,
            _ when user.IsAdmin => query,
            _ when isStaff => query.Where(r => departments.Contains(r.DepartmentId)),
            _ => query.Where(r => r.RequesterId == user.Id),
        };

        if (!string.IsNullOrWhiteSpace(q.Status) && Enum.TryParse<RequestStatus>(q.Status, true, out var status))
        {
            query = query.Where(r => r.Status == status);
        }

        if (!string.IsNullOrWhiteSpace(q.DepartmentId))
        {
            query = query.Where(r => r.DepartmentId == q.DepartmentId);
        }

        if (!string.IsNullOrWhiteSpace(q.Priority) && Enum.TryParse<RequestPriority>(q.Priority, true, out var priority))
        {
            query = query.Where(r => r.Priority == priority);
        }

        if (!string.IsNullOrWhiteSpace(term) && !textSearch && Request.TryParsePublicId(term, out var number))
        {
            query = query.Where(r => r.Number == number);
        }

        var total = await query.CountAsync(ct);
        var rows = await query
            .OrderByDescending(r => r.CreatedAt).ThenByDescending(r => r.Number)
            .Skip((page - 1) * size).Take(size)
            .Select(r => new
            {
                r.Number, r.Title, r.Category, r.DepartmentId, r.Priority, r.Status,
                r.RequesterId, RequesterName = r.Requester!.DisplayName, r.CreatedAt, r.UpdatedAt,
                HasRecommendation = r.Recommendations.Any(x => x.Status == RecommendationStatus.Proposed),
            })
            .ToListAsync(ct);

        var items = rows.Select(r => new RequestSummaryDto(
            Request.FormatPublicId(r.Number), r.Title, r.Category, r.DepartmentId, r.Priority.ToString(), r.Status.ToString(),
            new PersonRef(r.RequesterId, r.RequesterName), r.CreatedAt, r.UpdatedAt, r.HasRecommendation)).ToList();

        return new PagedResult<RequestSummaryDto>(items, page, size, total, (int)Math.Ceiling(total / (double)size));
    }

    public async Task<Result<RequestDetailDto>> GetAsync(AppUser user, string publicId, CancellationToken ct)
    {
        var request = await LoadAsync(publicId, ct);
        if (request is null)
        {
            return WorkflowError.NotFound(publicId);
        }

        if (!CanView(user, request))
        {
            return WorkflowError.Forbidden($"You do not have access to {request.PublicId}.");
        }

        return Result<RequestDetailDto>.Ok(await ToDetailAsync(user, request, ct));
    }

    public async Task<Result<RequestDetailDto>> CreateAsync(AppUser user, CreateRequestInput input, string? idempotencyKey, CancellationToken ct)
    {
        if (!user.HasRole(Roles.Requester))
        {
            return new WorkflowError("auth.role_required", "Only requesters can submit requests.", 403);
        }

        if (Validate(input) is { } invalid)
        {
            return invalid;
        }

        var key = NormalizeKey(idempotencyKey);
        if (key is not null)
        {
            var existing = await db.Requests.AsNoTracking()
                .Where(r => r.RequesterId == user.Id && r.IdempotencyKey == key)
                .Select(r => r.Number).FirstOrDefaultAsync(ct);
            if (existing != 0)
            {
                return await ReplayCreateAsync(user, existing, ct);
            }
        }

        var now = clock.GetUtcNow();
        var request = new Request
        {
            Id = Guid.NewGuid(),
            Title = input.Title.Trim(),
            Description = input.Description.Trim(),
            Category = input.Category,
            DepartmentId = input.DepartmentId,
            Priority = Enum.Parse<RequestPriority>(input.Priority ?? "Normal", true),
            RequesterId = user.Id,
            IdempotencyKey = key,
            CreatedAt = now,
            UpdatedAt = now,
        };
        db.Requests.Add(request);

        try
        {
            await db.SaveChangesAsync(ct);
        }
        catch (DbUpdateException ex) when (IsUniqueViolation(ex) && key is not null)
        {
            db.ChangeTracker.Clear();
            var number = await db.Requests.AsNoTracking()
                .Where(r => r.RequesterId == user.Id && r.IdempotencyKey == key).Select(r => r.Number).FirstAsync(ct);
            return await ReplayCreateAsync(user, number, ct);
        }

        AddAudit(request.Id, user.Id, "request.created", now, new { request = request.PublicId, department = request.DepartmentId });
        await NotifyDepartmentStaffAsync(request, "request.submitted", now, ct);
        await db.SaveChangesAsync(ct);
        RequestHubTelemetry.RequestsCreated.Add(1, new KeyValuePair<string, object?>("department", request.DepartmentId));
        logger.LogInformation("Request {RequestId} created by {UserId} for {Department}", request.PublicId, user.Id, request.DepartmentId);

        return Result<RequestDetailDto>.Ok(await ToDetailAsync(user, (await LoadAsync(request.PublicId, ct))!, ct));
    }

    public async Task<Result<CommentDto>> AddCommentAsync(AppUser user, string publicId, CommentInput input, CancellationToken ct)
    {
        var body = input.Body?.Trim() ?? "";
        if (body.Length is 0 or > 2000)
        {
            return WorkflowError.Validation("A comment must be between 1 and 2000 characters.");
        }

        var request = await LoadAsync(publicId, ct);
        if (request is null)
        {
            return WorkflowError.NotFound(publicId);
        }

        if (!CanView(user, request))
        {
            return WorkflowError.Forbidden($"You do not have access to {request.PublicId}.");
        }

        var now = clock.GetUtcNow();
        var comment = new Comment { Id = Guid.NewGuid(), RequestId = request.Id, AuthorId = user.Id, Body = body, CreatedAt = now };
        db.Comments.Add(comment);
        if (request.Status == RequestStatus.Submitted && user.IsStaffFor(request.DepartmentId) && request.RequesterId != user.Id)
        {
            request.Status = RequestStatus.InReview;
        }

        request.UpdatedAt = now;
        AddAudit(request.Id, user.Id, "comment.added", now, new { request = request.PublicId });
        if (request.RequesterId != user.Id)
        {
            AddNotification(request, request.RequesterId, "comment.added", now);
        }

        await db.SaveChangesAsync(ct);
        return Result<CommentDto>.Ok(new CommentDto(comment.Id, new PersonRef(user.Id, user.DisplayName), comment.Body, comment.CreatedAt));
    }

    public async Task<Result<DecisionDto>> DecideAsync(AppUser user, string publicId, DecisionInput input, string? idempotencyKey, CancellationToken ct)
    {
        if (!Enum.TryParse<DecisionOutcome>(input.Outcome, true, out var outcome))
        {
            return WorkflowError.Validation("Outcome must be 'Approved' or 'Rejected'.");
        }

        var comment = input.Comment?.Trim();
        if (outcome == DecisionOutcome.Rejected && string.IsNullOrEmpty(comment))
        {
            return WorkflowError.Validation("A comment is required when rejecting a request.");
        }

        if (comment is { Length: > 2000 })
        {
            return WorkflowError.Validation("The decision comment must be at most 2000 characters.");
        }

        var key = NormalizeKey(idempotencyKey);
        var request = await LoadAsync(publicId, ct);
        if (request is null)
        {
            return WorkflowError.NotFound(publicId);
        }

        if (!user.HasRole(Roles.Approver))
        {
            return new WorkflowError("decision.not_approver", "Only approvers can record a decision.", 403);
        }

        if (!user.CanAccessDepartment(request.DepartmentId))
        {
            return WorkflowError.Forbidden($"You cannot decide requests routed to {request.DepartmentId}.");
        }

        if (request.RequesterId == user.Id)
        {
            return new WorkflowError("decision.self_approval", "You cannot decide on your own request.", 403);
        }

        if (request.Decision is { } existing)
        {
            return ExistingDecisionOutcome(existing, user, key);
        }

        var now = clock.GetUtcNow();
        var decision = new ApprovalDecision
        {
            Id = Guid.NewGuid(),
            RequestId = request.Id,
            Outcome = outcome,
            DecidedById = user.Id,
            Comment = string.IsNullOrEmpty(comment) ? null : comment,
            IdempotencyKey = key,
            DecidedAt = now,
        };
        db.Decisions.Add(decision);
        request.Status = outcome == DecisionOutcome.Approved ? RequestStatus.Approved : RequestStatus.Rejected;
        request.UpdatedAt = now;
        AddAudit(request.Id, user.Id, "decision.recorded", now, new { request = request.PublicId, outcome = outcome.ToString() });
        AddNotification(request, request.RequesterId, "request.decided", now, new { outcome = outcome.ToString() });

        try
        {
            await db.SaveChangesAsync(ct);
        }
        catch (Exception ex) when (ex is DbUpdateConcurrencyException || (ex is DbUpdateException dbEx && IsUniqueViolation(dbEx)))
        {
            // A concurrent decision won the race (double click, retry, or a second approver).
            db.ChangeTracker.Clear();
            RequestHubTelemetry.DecisionConflicts.Add(1);
            var winner = await db.Decisions.AsNoTracking().Include(d => d.DecidedBy)
                .FirstAsync(d => d.RequestId == request.Id, ct);
            return ExistingDecisionOutcome(winner, user, key);
        }

        RequestHubTelemetry.DecisionsRecorded.Add(1, new KeyValuePair<string, object?>("outcome", outcome.ToString()));
        logger.LogInformation("Decision {Outcome} recorded on {RequestId} by {UserId}", outcome, request.PublicId, user.Id);
        return Result<DecisionDto>.Ok(new DecisionDto(outcome.ToString(), new PersonRef(user.Id, user.DisplayName), decision.Comment, now));
    }

    public async Task<Result<RequestDetailDto>> RerouteAsync(AppUser user, string publicId, RoutingInput input, CancellationToken ct)
    {
        var request = await LoadAsync(publicId, ct);
        if (request is null)
        {
            return WorkflowError.NotFound(publicId);
        }

        if (!(user.HasRole(Roles.Reviewer) || user.IsAdmin))
        {
            return new WorkflowError("auth.role_required", "Only reviewers can change routing.", 403);
        }

        if (!user.CanAccessDepartment(request.DepartmentId) || !user.CanAccessDepartment(input.DepartmentId))
        {
            return WorkflowError.Forbidden("You can only route between departments you have access to.");
        }

        if (profile.Departments.All(d => d.Id != input.DepartmentId))
        {
            return WorkflowError.Validation($"Unknown department '{input.DepartmentId}'.");
        }

        if (request.Status.IsTerminal())
        {
            return new WorkflowError("request.terminal", $"{request.PublicId} is {request.Status} and can no longer be rerouted.", 409);
        }

        if (request.DepartmentId == input.DepartmentId)
        {
            return WorkflowError.Validation($"{request.PublicId} is already routed to {input.DepartmentId}.");
        }

        var now = clock.GetUtcNow();
        var from = request.DepartmentId;
        request.DepartmentId = input.DepartmentId;
        request.UpdatedAt = now;
        if (request.Status == RequestStatus.Submitted)
        {
            request.Status = RequestStatus.InReview;
        }

        AddAudit(request.Id, user.Id, "routing.changed", now, new { request = request.PublicId, from, to = input.DepartmentId, reason = input.Reason });
        await NotifyDepartmentStaffAsync(request, "request.routed", now, ct);
        try
        {
            await db.SaveChangesAsync(ct);
        }
        catch (DbUpdateConcurrencyException)
        {
            return new WorkflowError("request.concurrent_update", $"{request.PublicId} was changed by someone else. Reload and retry.", 409);
        }

        return Result<RequestDetailDto>.Ok(await ToDetailAsync(user, request, ct));
    }

    public async Task<Result<RecommendationDto>> RecommendAsync(AppUser user, string publicId, CancellationToken ct)
    {
        var request = await LoadAsync(publicId, ct);
        if (request is null)
        {
            return WorkflowError.NotFound(publicId);
        }

        if (!user.IsStaffFor(request.DepartmentId))
        {
            return WorkflowError.Forbidden($"You cannot triage requests routed to {request.DepartmentId}.");
        }

        if (request.Status.IsTerminal())
        {
            return new WorkflowError("request.terminal", $"{request.PublicId} is {request.Status}; triage is closed.", 409);
        }

        var tools = new ScopedTriageTools(this, user, request);
        var context = new TriageContext(
            request.PublicId, request.Title, request.Description, request.Category, request.DepartmentId, request.Priority.ToString(),
            profile.Policies, profile.Departments.Select(d => new TriageDepartment(d.Id, d.En)).ToList(), tools);

        using var activity = RequestHubTelemetry.ActivitySource.StartActivity("triage.recommend");
        activity?.SetTag("requesthub.request_id", request.PublicId);
        activity?.SetTag("requesthub.triage.provider", triage.Id);
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(ct);
        timeout.CancelAfter(TimeSpan.FromSeconds(Math.Max(1, triageOptions.Value.TimeoutSeconds)));
        var started = Stopwatch.GetTimestamp();
        TriageResult result;
        try
        {
            result = await triage.RecommendAsync(context, timeout.Token);
        }
        catch (OperationCanceledException) when (!ct.IsCancellationRequested)
        {
            return await TriageFailedAsync(request, user, "triage.timeout", "The triage provider did not respond in time. Try again or route manually.", 504, ct);
        }
        catch (TriageUnavailableException ex)
        {
            logger.LogWarning(ex, "Triage provider {Provider} unavailable", triage.Id);
            return await TriageFailedAsync(request, user, "triage.unavailable", "The triage assistant is unavailable. Route the request manually.", 503, ct);
        }
        catch (TriageInvalidOutputException ex)
        {
            logger.LogWarning("Triage provider {Provider} returned invalid output: {Reason}", triage.Id, ex.Message);
            return await TriageFailedAsync(request, user, "triage.invalid_output", $"The triage assistant returned an unusable recommendation: {ex.Message}", 502, ct);
        }
        finally
        {
            RequestHubTelemetry.TriageDuration.Record(Stopwatch.GetElapsedTime(started).TotalMilliseconds,
                new KeyValuePair<string, object?>("provider", triage.Id));
        }

        if (ValidateRecommendation(result) is { } problem)
        {
            logger.LogWarning("Rejected recommendation from {Provider}: {Problem}", triage.Id, problem);
            return await TriageFailedAsync(request, user, "triage.invalid_output", problem, 502, ct);
        }

        var now = clock.GetUtcNow();
        // Deterministic guard: a person must decide when policies send the request to different departments, either because
        // the cost is above the spend threshold while the category routes elsewhere, or because the cited routing policies
        // disagree. Model output cannot skip this.
        var conflictGuard = !result.NeedsHumanReview && (SpendConflict(request) || CitedRoutingConflict(result.PolicyIds));
        if (conflictGuard)
        {
            result = result with
            {
                NeedsHumanReview = true,
                Rationale = $"{result.Rationale.Trim()} [Guard: policies route this request to different departments; human review required.]",
            };
        }

        foreach (var previous in request.Recommendations.Where(x => x.Status == RecommendationStatus.Proposed))
        {
            previous.Status = RecommendationStatus.Superseded;
        }

        var recommendation = new TriageRecommendation
        {
            Id = Guid.NewGuid(),
            RequestId = request.Id,
            Provider = triage.Id,
            IsSample = triage.IsSample,
            SuggestedDepartmentId = result.SuggestedDepartmentId,
            SuggestedPriority = Enum.Parse<RequestPriority>(result.SuggestedPriority, true),
            Rationale = result.ClarifyingQuestion is null ? result.Rationale.Trim() : $"{result.Rationale.Trim()} Question: {result.ClarifyingQuestion.Trim()}",
            PolicyRefs = result.PolicyIds.Select(id => profile.FindPolicy(id)!.Ref).Distinct().ToList(),
            Confidence = Math.Round(result.Confidence, 2),
            NeedsHumanReview = result.NeedsHumanReview,
            DepartmentAtRecommendation = request.DepartmentId,
            CreatedById = user.Id,
            CreatedAt = now,
            ProviderTraceId = result.ProviderTraceId,
        };
        db.Recommendations.Add(recommendation);
        AddAudit(request.Id, user.Id, "triage.recommended", now, new
        {
            request = request.PublicId,
            provider = triage.Id,
            isSample = triage.IsSample,
            suggestedDepartment = recommendation.SuggestedDepartmentId,
            policyRefs = recommendation.PolicyRefs,
            providerTraceId = result.ProviderTraceId,
            guard = conflictGuard ? "policy-conflict" : null,
        });
        await db.SaveChangesAsync(ct);
        RequestHubTelemetry.TriageCalls.Add(1, new KeyValuePair<string, object?>("provider", triage.Id), new KeyValuePair<string, object?>("outcome", "ok"));
        return Result<RecommendationDto>.Ok(ToDto(recommendation, new PersonRef(user.Id, user.DisplayName)));
    }

    public async Task<Result<IReadOnlyList<RecommendationDto>>> ListRecommendationsAsync(AppUser user, string publicId, CancellationToken ct)
    {
        var request = await LoadAsync(publicId, ct);
        if (request is null)
        {
            return WorkflowError.NotFound(publicId);
        }

        if (!CanView(user, request))
        {
            return WorkflowError.Forbidden($"You do not have access to {request.PublicId}.");
        }

        var names = await NamesAsync(request.Recommendations.Select(r => r.CreatedById), ct);
        IReadOnlyList<RecommendationDto> list = request.Recommendations.OrderByDescending(r => r.CreatedAt)
            .Select(r => ToDto(r, new PersonRef(r.CreatedById, names.GetValueOrDefault(r.CreatedById, r.CreatedById)))).ToList();
        return Result<IReadOnlyList<RecommendationDto>>.Ok(list);
    }

    public async Task<Result<IReadOnlyList<AuditEventDto>>> HistoryAsync(AppUser user, string publicId, CancellationToken ct)
    {
        var request = await LoadAsync(publicId, ct);
        if (request is null)
        {
            return WorkflowError.NotFound(publicId);
        }

        if (!CanView(user, request))
        {
            return WorkflowError.Forbidden($"You do not have access to {request.PublicId}.");
        }

        var events = await db.AuditEvents.AsNoTracking().Where(a => a.RequestId == request.Id)
            .OrderBy(a => a.OccurredAt).ThenBy(a => a.Id).ToListAsync(ct);
        var names = await NamesAsync(events.Select(e => e.Actor), ct);
        IReadOnlyList<AuditEventDto> list = events.Select(e => new AuditEventDto(
            e.Id, e.Action, new PersonRef(e.Actor, names.GetValueOrDefault(e.Actor, e.Actor)), e.OccurredAt,
            JsonDocument.Parse(e.Details).RootElement.Clone(), e.CorrelationId)).ToList();
        return Result<IReadOnlyList<AuditEventDto>>.Ok(list);
    }

    /// <summary>Loads a request the caller may view (used by attachment endpoints).</summary>
    public async Task<Result<Request>> GetAccessibleAsync(AppUser user, string publicId, bool forUpload, CancellationToken ct)
    {
        var request = await LoadAsync(publicId, ct);
        if (request is null)
        {
            return WorkflowError.NotFound(publicId);
        }

        if (!CanView(user, request))
        {
            return WorkflowError.Forbidden($"You do not have access to {request.PublicId}.");
        }

        if (forUpload && request.Status.IsTerminal())
        {
            return new WorkflowError("request.terminal", $"{request.PublicId} is {request.Status}; attachments are closed.", 409);
        }

        return Result<Request>.Ok(request);
    }

    public void RecordAudit(Guid? requestId, string actor, string action, object details) =>
        AddAudit(requestId, actor, action, clock.GetUtcNow(), details);

    public Task SaveAsync(CancellationToken ct) => db.SaveChangesAsync(ct);

    public static bool CanView(AppUser user, Request request) =>
        user.IsAdmin || request.RequesterId == user.Id || user.IsStaffFor(request.DepartmentId);

    public static PermissionsDto PermissionsFor(AppUser user, Request request)
    {
        var terminal = request.Status.IsTerminal();
        var canView = CanView(user, request);
        string? blocked = null;
        if (!user.HasRole(Roles.Approver)) blocked = "not_approver";
        else if (!user.CanAccessDepartment(request.DepartmentId)) blocked = "department";
        else if (request.RequesterId == user.Id) blocked = "self_approval";
        else if (terminal) blocked = "terminal";

        return new PermissionsDto(
            CanComment: canView,
            CanUpload: canView && !terminal,
            CanTriage: user.IsStaffFor(request.DepartmentId) && !terminal,
            CanRoute: (user.HasRole(Roles.Reviewer) || user.IsAdmin) && user.CanAccessDepartment(request.DepartmentId) && !terminal,
            CanDecide: blocked is null,
            DecideBlockedReason: blocked);
    }

    internal async Task<Request?> LoadAsync(string publicId, CancellationToken ct)
    {
        if (!Request.TryParsePublicId(publicId, out var number))
        {
            return null;
        }

        return await db.Requests
            .Include(r => r.Requester)
            .Include(r => r.Decision).ThenInclude(d => d!.DecidedBy)
            .Include(r => r.Comments).ThenInclude(c => c.Author)
            .Include(r => r.Attachments)
            .Include(r => r.Recommendations)
            .AsSplitQuery()
            .FirstOrDefaultAsync(r => r.Number == number, ct);
    }

    internal async Task<RequestDetailDto> ToDetailAsync(AppUser user, Request r, CancellationToken ct)
    {
        var latest = r.Recommendations.Where(x => x.Status != RecommendationStatus.Superseded).OrderByDescending(x => x.CreatedAt).FirstOrDefault();
        var people = await NamesAsync(r.Attachments.Select(a => a.UploadedById).Concat(latest is null ? [] : [latest.CreatedById]), ct);
        return new RequestDetailDto(
            r.PublicId, r.Title, r.Description, r.Category, r.DepartmentId, r.Priority.ToString(), r.Status.ToString(),
            new PersonRef(r.RequesterId, r.Requester?.DisplayName ?? r.RequesterId), r.CreatedAt, r.UpdatedAt, r.Version.ToString(),
            r.Decision is { } d ? new DecisionDto(d.Outcome.ToString(), new PersonRef(d.DecidedById, d.DecidedBy?.DisplayName ?? d.DecidedById), d.Comment, d.DecidedAt) : null,
            latest is null ? null : ToDto(latest, new PersonRef(latest.CreatedById, people.GetValueOrDefault(latest.CreatedById, latest.CreatedById))),
            r.Comments.OrderBy(c => c.CreatedAt).Select(c => new CommentDto(c.Id, new PersonRef(c.AuthorId, c.Author?.DisplayName ?? c.AuthorId), c.Body, c.CreatedAt)).ToList(),
            r.Attachments.OrderBy(a => a.UploadedAt).Select(a => new AttachmentDto(a.Id, a.FileName, a.ContentType, a.SizeBytes, a.Sha256,
                new PersonRef(a.UploadedById, people.GetValueOrDefault(a.UploadedById, a.UploadedById)), a.UploadedAt,
                $"/api/requests/{r.PublicId}/attachments/{a.Id}/content")).ToList(),
            PermissionsFor(user, r));
    }

    internal static RecommendationDto ToDto(TriageRecommendation r, PersonRef createdBy) => new(
        r.Id, r.Provider, r.IsSample, r.SuggestedDepartmentId, r.SuggestedPriority.ToString(), r.Rationale,
        r.PolicyRefs.Select(p => p.Split('@', 2)).Select(p => new PolicyRefDto(p[0], p.Length > 1 ? p[1] : "")).ToList(),
        r.Confidence, r.NeedsHumanReview, r.Status.ToString(), r.DepartmentAtRecommendation, createdBy, r.CreatedAt, r.ProviderTraceId);

    private async Task<Result<RecommendationDto>> TriageFailedAsync(Request request, AppUser user, string code, string message, int status, CancellationToken ct)
    {
        AddAudit(request.Id, user.Id, "triage.failed", clock.GetUtcNow(), new { request = request.PublicId, provider = triage.Id, code });
        await db.SaveChangesAsync(ct);
        RequestHubTelemetry.TriageCalls.Add(1, new KeyValuePair<string, object?>("provider", triage.Id), new KeyValuePair<string, object?>("outcome", code));
        return new WorkflowError(code, message, status);
    }

    private bool CitedRoutingConflict(IReadOnlyList<string> policyIds) =>
        policyIds.Select(id => profile.FindPolicy(id))
            .Where(p => p is { Kind: "routing" })
            .Select(p => p!.RouteTo)
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .Count() > 1;

    private bool SpendConflict(Request request)
    {
        var amount = SampleRulesTriageProvider.EstimatedAmount($"{request.Title}\n{request.Description}");
        return profile.Policies
            .Where(p => p.Kind == "spend" && p.Threshold is { } threshold && amount > threshold)
            .Any(spend => profile.Policies.Any(p => p.Kind == "routing"
                && p.Categories.Contains(request.Category, StringComparer.OrdinalIgnoreCase)
                && !string.Equals(p.RouteTo, spend.RouteTo, StringComparison.OrdinalIgnoreCase)));
    }

    private string? ValidateRecommendation(TriageResult result)
    {
        if (profile.Departments.All(d => d.Id != result.SuggestedDepartmentId))
        {
            return $"unknown department '{result.SuggestedDepartmentId}'";
        }

        if (!Enum.TryParse<RequestPriority>(result.SuggestedPriority, true, out _))
        {
            return $"unknown priority '{result.SuggestedPriority}'";
        }

        if (result.PolicyIds.Count == 0)
        {
            return "no policy citation";
        }

        var unknown = result.PolicyIds.Where(id => profile.FindPolicy(id) is null).ToList();
        if (unknown.Count > 0)
        {
            return $"cites unknown policies: {string.Join(", ", unknown)}";
        }

        if (string.IsNullOrWhiteSpace(result.Rationale) || result.Rationale.Length > 1500)
        {
            return "rationale is missing or too long";
        }

        if (result.Confidence is < 0 or > 1)
        {
            return "confidence must be between 0 and 1";
        }

        // POL-GOV-001: a recommendation must never state or imply an approval decision.
        if (ApprovalClaim().IsMatch(result.Rationale) || ApprovalClaim().IsMatch(result.ClarifyingQuestion ?? ""))
        {
            return "rationale claims an approval decision (POL-GOV-001)";
        }

        return null;
    }

    private Result<DecisionDto> ExistingDecisionOutcome(ApprovalDecision existing, AppUser user, string? key)
    {
        var dto = new DecisionDto(existing.Outcome.ToString(), new PersonRef(existing.DecidedById, existing.DecidedBy?.DisplayName ?? existing.DecidedById), existing.Comment, existing.DecidedAt);
        if (key is not null && existing.IdempotencyKey == key && existing.DecidedById == user.Id)
        {
            return Result<DecisionDto>.Ok(dto, replayed: true);
        }

        return new WorkflowError("decision.already_decided", $"This request was already {existing.Outcome.ToString().ToLowerInvariant()}.", 409, new { decision = dto });
    }

    private async Task<Result<RequestDetailDto>> ReplayCreateAsync(AppUser user, int number, CancellationToken ct)
    {
        var request = await LoadAsync(Request.FormatPublicId(number), ct);
        return Result<RequestDetailDto>.Ok(await ToDetailAsync(user, request!, ct), replayed: true);
    }

    private WorkflowError? Validate(CreateRequestInput input)
    {
        var title = input.Title?.Trim() ?? "";
        var description = input.Description?.Trim() ?? "";
        if (title.Length is < 5 or > 120) return WorkflowError.Validation("Title must be between 5 and 120 characters.");
        if (description.Length is < 10 or > 4000) return WorkflowError.Validation("Description must be between 10 and 4000 characters.");
        if (profile.Categories.All(c => c.Id != input.Category)) return WorkflowError.Validation($"Unknown category '{input.Category}'.");
        if (profile.Departments.All(d => d.Id != input.DepartmentId)) return WorkflowError.Validation($"Unknown department '{input.DepartmentId}'.");
        if (input.Priority is not null && !Enum.TryParse<RequestPriority>(input.Priority, true, out _)) return WorkflowError.Validation($"Unknown priority '{input.Priority}'.");
        return null;
    }

    private async Task NotifyDepartmentStaffAsync(Request request, string type, DateTimeOffset now, CancellationToken ct)
    {
        var staff = await db.Users.AsNoTracking()
            .Where(u => u.Roles.Contains(Roles.Reviewer) && u.DepartmentAccess.Contains(request.DepartmentId) && u.Id != request.RequesterId)
            .Select(u => u.Id).ToListAsync(ct);
        foreach (var recipient in staff)
        {
            AddNotification(request, recipient, type, now);
        }
    }

    private void AddNotification(Request request, string recipient, string type, DateTimeOffset now, object? extra = null) =>
        db.Notifications.Add(new Notification
        {
            Id = Guid.NewGuid(),
            RequestId = request.Id,
            Recipient = recipient,
            Type = type,
            Payload = JsonSerializer.Serialize(new { request = request.PublicId, title = request.Title, extra }),
            CreatedAt = now,
            NextAttemptAt = now,
            CorrelationId = RequestHubTelemetry.CorrelationId,
        });

    private void AddAudit(Guid? requestId, string actor, string action, DateTimeOffset at, object details) =>
        db.AuditEvents.Add(new AuditEvent
        {
            RequestId = requestId,
            Actor = actor,
            Action = action,
            Details = JsonSerializer.Serialize(details),
            CorrelationId = RequestHubTelemetry.CorrelationId,
            OccurredAt = at,
        });

    private async Task<Dictionary<string, string>> NamesAsync(IEnumerable<string> ids, CancellationToken ct)
    {
        var distinct = ids.Distinct().ToList();
        if (distinct.Count == 0)
        {
            return [];
        }

        return await db.Users.AsNoTracking().Where(u => distinct.Contains(u.Id)).ToDictionaryAsync(u => u.Id, u => u.DisplayName, ct);
    }

    private static string? NormalizeKey(string? key) =>
        string.IsNullOrWhiteSpace(key) ? null : key.Trim().Length > 100 ? key.Trim()[..100] : key.Trim();

    private static string EscapeLike(string value) =>
        value.Replace("\\", "\\\\", StringComparison.Ordinal).Replace("%", "\\%", StringComparison.Ordinal).Replace("_", "\\_", StringComparison.Ordinal);

    private static bool IsUniqueViolation(DbUpdateException ex) =>
        ex.InnerException is PostgresException { SqlState: PostgresErrorCodes.UniqueViolation };

    [GeneratedRegex(@"\b(is|has been|was|been|i|we)\s+(auto-?)?approved\b|\bauto-?approv|\bapproved\s+(this|the)\s+request\b|\bI\s+approve\b", RegexOptions.IgnoreCase)]
    private static partial Regex ApprovalClaim();

    /// <summary>Tools for live triage agents. Only the request being triaged is readable; every call is audited.</summary>
    private sealed class ScopedTriageTools(RequestWorkflow workflow, AppUser user, Request current) : ITriageTools
    {
        private static readonly JsonSerializerOptions Json = new(JsonSerializerDefaults.Web);

        public Task<string> GetRequestAsync(string requestId, CancellationToken cancellationToken)
        {
            if (!string.Equals(requestId?.Trim(), current.PublicId, StringComparison.OrdinalIgnoreCase))
            {
                workflow.RecordAudit(current.Id, user.Id, "triage.tool_call", new { tool = "get_request", requestId, outcome = "denied" });
                return Task.FromResult(JsonSerializer.Serialize(new
                {
                    error = "not_permitted",
                    message = $"Only {current.PublicId}, the request being triaged, can be read.",
                }, Json));
            }

            // Data minimization (BR-3 / STD-SEC-002): only these fields may reach an AI service.
            // No comments, attachments, or people data.
            workflow.RecordAudit(current.Id, user.Id, "triage.tool_call", new { tool = "get_request", requestId, outcome = "ok" });
            return Task.FromResult(JsonSerializer.Serialize(new
            {
                id = current.PublicId,
                title = current.Title,
                description = current.Description,
                category = current.Category,
                currentDepartment = current.DepartmentId,
                priority = current.Priority.ToString(),
            }, Json));
        }

        public Task<string> GetRoutingPoliciesAsync(string? category, CancellationToken cancellationToken)
        {
            workflow.RecordAudit(current.Id, user.Id, "triage.tool_call", new { tool = "get_routing_policies", category, outcome = "ok" });
            var policies = workflow.Profile.Policies
                .Where(p => string.IsNullOrWhiteSpace(category) || p.Categories.Count == 0 || p.Categories.Contains(category, StringComparer.OrdinalIgnoreCase))
                .Select(p => new { id = p.Id, version = p.Version, kind = p.Kind, title = p.Title, text = p.Text, routeTo = p.RouteTo, threshold = p.Threshold });
            return Task.FromResult(JsonSerializer.Serialize(new { policies }, Json));
        }
    }
}
