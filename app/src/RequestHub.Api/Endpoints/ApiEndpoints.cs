using System.Reflection;
using System.Security.Cryptography;
using Microsoft.AspNetCore.Http.HttpResults;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Options;
using RequestHub.Api.Auth;
using RequestHub.Api.Storage;
using RequestHub.Core.Data;
using RequestHub.Core.Domain;
using RequestHub.Core.Notifications;
using RequestHub.Core.Services;
using RequestHub.Core.Triage;

namespace RequestHub.Api.Endpoints;

public static class ApiEndpoints
{
    public const string ContractVersion = "requesthub.v1";
    public const string IdempotencyHeader = "Idempotency-Key";

    public static void MapRequestHubApi(this WebApplication app)
    {
        app.MapGet("/api/meta", GetMeta).WithTags("Meta").WithSummary("Build, environment, and contract metadata (no secrets).");
        app.MapGet("/api/personas", GetPersonas).WithTags("Meta").WithSummary("Synthetic personas for the local persona switcher (Development auth mode only).");

        var api = app.MapGroup("/api").RequireAuthorization().WithTags("RequestHub");
        api.MapGet("/me", (HttpContext ctx) => TypedResults.Ok(ToMe(ctx.User.ToAppUser()))).WithSummary("The signed-in user, roles, and department access.");
        api.MapGet("/departments", GetDepartments);
        api.MapGet("/categories", GetCategories);
        api.MapGet("/policies", GetPolicies).WithSummary("Approved routing policies with ids and versions used by triage recommendations.");

        api.MapGet("/requests", ListRequests).WithSummary("Paged, filtered list. scope=mine|queue|all.");
        api.MapPost("/requests", CreateRequest).WithSummary("Submit a request. Optional Idempotency-Key header makes retries safe.")
            .Produces<RequestDetailDto>(StatusCodes.Status201Created).Produces<RequestDetailDto>().ProducesValidationProblem().ProducesProblem(StatusCodes.Status403Forbidden);
        api.MapGet("/requests/{id}", GetRequest).WithSummary("Request detail with decision, latest recommendation, comments, attachments, and the caller's permissions.")
            .Produces<RequestDetailDto>().ProducesProblem(StatusCodes.Status403Forbidden).ProducesProblem(StatusCodes.Status404NotFound);
        api.MapPost("/requests/{id}/comments", AddComment)
            .Produces<CommentDto>(StatusCodes.Status201Created).ProducesProblem(StatusCodes.Status400BadRequest).ProducesProblem(StatusCodes.Status403Forbidden).ProducesProblem(StatusCodes.Status404NotFound);
        api.MapPost("/requests/{id}/decisions", Decide).WithSummary("Approve or reject. One decision per request; requesters cannot decide their own request. Idempotency-Key makes retries return the original decision.")
            .Produces<DecisionDto>(StatusCodes.Status201Created).Produces<DecisionDto>().ProducesProblem(StatusCodes.Status400BadRequest)
            .ProducesProblem(StatusCodes.Status403Forbidden).ProducesProblem(StatusCodes.Status404NotFound).ProducesProblem(StatusCodes.Status409Conflict);
        api.MapPut("/requests/{id}/routing", Reroute).WithSummary("Reviewer changes the routed department (audited).")
            .Produces<RequestDetailDto>().ProducesProblem(StatusCodes.Status400BadRequest).ProducesProblem(StatusCodes.Status403Forbidden)
            .ProducesProblem(StatusCodes.Status404NotFound).ProducesProblem(StatusCodes.Status409Conflict);
        api.MapGet("/requests/{id}/history", History).WithSummary("Audit history for the request.")
            .Produces<List<AuditEventDto>>().ProducesProblem(StatusCodes.Status403Forbidden).ProducesProblem(StatusCodes.Status404NotFound);
        api.MapGet("/requests/{id}/attachments", ListAttachments)
            .Produces<List<AttachmentDto>>().ProducesProblem(StatusCodes.Status403Forbidden).ProducesProblem(StatusCodes.Status404NotFound);
        api.MapPost("/requests/{id}/attachments", UploadAttachment).DisableAntiforgery().WithSummary("Upload one file (multipart field 'file'). Allow-listed types, 5 MB max.")
            .Produces<AttachmentDto>(StatusCodes.Status201Created).ProducesProblem(StatusCodes.Status400BadRequest).ProducesProblem(StatusCodes.Status403Forbidden)
            .ProducesProblem(StatusCodes.Status404NotFound).ProducesProblem(StatusCodes.Status409Conflict).ProducesProblem(StatusCodes.Status415UnsupportedMediaType);
        api.MapGet("/requests/{id}/attachments/{attachmentId:guid}/content", DownloadAttachment).WithSummary("Authorized download.")
            .Produces(StatusCodes.Status200OK, contentType: "application/octet-stream").ProducesProblem(StatusCodes.Status403Forbidden).ProducesProblem(StatusCodes.Status404NotFound);
        api.MapPost("/requests/{id}/triage-recommendations", Recommend).WithSummary("Ask the configured triage provider for an advisory routing recommendation. Never approves.")
            .Produces<RecommendationDto>(StatusCodes.Status201Created).ProducesProblem(StatusCodes.Status403Forbidden).ProducesProblem(StatusCodes.Status404NotFound)
            .ProducesProblem(StatusCodes.Status409Conflict).ProducesProblem(StatusCodes.Status502BadGateway).ProducesProblem(StatusCodes.Status503ServiceUnavailable)
            .ProducesProblem(StatusCodes.Status504GatewayTimeout);
        api.MapGet("/requests/{id}/triage-recommendations", ListRecommendations)
            .Produces<List<RecommendationDto>>().ProducesProblem(StatusCodes.Status403Forbidden).ProducesProblem(StatusCodes.Status404NotFound);
        api.MapPost("/requests/{id}/triage-recommendations/{recommendationId:guid}/confirm", ConfirmRecommendation)
            .WithSummary("Reviewer confirms a routing recommendation without making an approval decision.")
            .Produces<RequestDetailDto>().ProducesProblem(StatusCodes.Status403Forbidden).ProducesProblem(StatusCodes.Status404NotFound)
            .ProducesProblem(StatusCodes.Status409Conflict);

        var admin = api.MapGroup("/admin").RequireAuthorization("Admin").WithTags("Admin");
        admin.MapPost("/reset", ResetDemo).WithSummary("Delete and reseed all demo data in this environment's database (Demo:AllowReset must be true).")
            .Produces(StatusCodes.Status200OK).ProducesProblem(StatusCodes.Status403Forbidden);
        admin.MapGet("/notifications/backlog", Backlog).WithSummary("Pending notification count and oldest pending age.");
    }

    private static Ok<MetaDto> GetMeta(IConfiguration config, IHostEnvironment env, ITriageProvider triage, RequestWorkflow workflow) =>
        TypedResults.Ok(new MetaDto(
            "RequestHub",
            typeof(ApiEndpoints).Assembly.GetCustomAttribute<AssemblyInformationalVersionAttribute>()?.InformationalVersion ?? "1.0.0",
            config["BUILD_SHA"] ?? config["App:BuildSha"] ?? "local",
            env.EnvironmentName,
            workflow.Profile.Id,
            ContractVersion,
            triage.Id,
            AuthSetup.ModeName(config),
            config["Demo:Locale"] ?? "en"));

    private static async Task<Results<Ok<List<PersonaDto>>, NotFound>> GetPersonas(IConfiguration config, RequestHubDbContext db, CancellationToken ct)
    {
        if (AuthSetup.ModeName(config) != AuthSettings.DevelopmentMode)
        {
            return TypedResults.NotFound();
        }

        var users = await db.Users.AsNoTracking().Where(u => u.IsSynthetic).OrderBy(u => u.Id).ToListAsync(ct);
        return TypedResults.Ok(users.Select(u => new PersonaDto(u.Id, u.DisplayName, u.Roles, u.DepartmentAccess)).ToList());
    }

    private static Ok<List<DepartmentDto>> GetDepartments(RequestWorkflow workflow) =>
        TypedResults.Ok(workflow.Profile.Departments.Select(d => new DepartmentDto(d.Id, d.En, d.Fr)).ToList());

    private static Ok<List<CategoryDto>> GetCategories(RequestWorkflow workflow) =>
        TypedResults.Ok(workflow.Profile.Categories.Select(c => new CategoryDto(c.Id, c.En, c.Fr)).ToList());

    private static Ok<List<PolicyDto>> GetPolicies(RequestWorkflow workflow) =>
        TypedResults.Ok(workflow.Profile.Policies.Select(p => new PolicyDto(p.Id, p.Version, p.Kind, p.Title, p.Text, p.RouteTo, p.Priority, p.Threshold, p.Ref)).ToList());

    private static async Task<Ok<PagedResult<RequestSummaryDto>>> ListRequests(
        HttpContext ctx, RequestWorkflow workflow, IOptionsMonitor<FaultOptions> faults, TimeProvider clock, CancellationToken ct,
        string? scope = "queue", string? status = null, string? department = null, string? priority = null, string? q = null, int page = 1, int pageSize = 20)
    {
        var fault = faults.CurrentValue;
        if (fault.QueueDelayMs > 0 && fault.IsActive(clock))
        {
            System.Diagnostics.Activity.Current?.SetTag("requesthub.fault.queue_delay_ms", fault.QueueDelayMs);
            await Task.Delay(fault.QueueDelayMs, ct);
        }

        return TypedResults.Ok(await workflow.ListAsync(ctx.User.ToAppUser(), new RequestQuery(scope ?? "queue", status, department, priority, q, page, pageSize), ct));
    }

    private static async Task<IResult> CreateRequest(HttpContext ctx, CreateRequestInput input, RequestWorkflow workflow, CancellationToken ct)
    {
        var result = await workflow.CreateAsync(ctx.User.ToAppUser(), input, ctx.Request.Headers[IdempotencyHeader], ct);
        if (!result.IsSuccess) return Problem(result.Error!);
        return result.Replayed
            ? TypedResults.Ok(result.Value)
            : TypedResults.Created($"/api/requests/{result.Value!.Id}", result.Value);
    }

    private static async Task<IResult> GetRequest(HttpContext ctx, string id, RequestWorkflow workflow, CancellationToken ct)
    {
        var result = await workflow.GetAsync(ctx.User.ToAppUser(), id, ct);
        if (!result.IsSuccess) return Problem(result.Error!);
        ctx.Response.Headers.ETag = $"\"{result.Value!.Version}\"";
        return TypedResults.Ok(result.Value);
    }

    private static async Task<IResult> AddComment(HttpContext ctx, string id, CommentInput input, RequestWorkflow workflow, CancellationToken ct)
    {
        var result = await workflow.AddCommentAsync(ctx.User.ToAppUser(), id, input, ct);
        return result.IsSuccess ? TypedResults.Created($"/api/requests/{id}", result.Value) : Problem(result.Error!);
    }

    private static async Task<IResult> Decide(HttpContext ctx, string id, DecisionInput input, RequestWorkflow workflow, CancellationToken ct)
    {
        var result = await workflow.DecideAsync(ctx.User.ToAppUser(), id, input, ctx.Request.Headers[IdempotencyHeader], ct);
        if (!result.IsSuccess) return Problem(result.Error!);
        return result.Replayed ? TypedResults.Ok(result.Value) : TypedResults.Created($"/api/requests/{id}", result.Value);
    }

    private static async Task<IResult> Reroute(HttpContext ctx, string id, RoutingInput input, RequestWorkflow workflow, CancellationToken ct)
    {
        var result = await workflow.RerouteAsync(ctx.User.ToAppUser(), id, input, ct);
        return result.IsSuccess ? TypedResults.Ok(result.Value) : Problem(result.Error!);
    }

    private static async Task<IResult> History(HttpContext ctx, string id, RequestWorkflow workflow, CancellationToken ct)
    {
        var result = await workflow.HistoryAsync(ctx.User.ToAppUser(), id, ct);
        return result.IsSuccess ? TypedResults.Ok(result.Value) : Problem(result.Error!);
    }

    private static async Task<IResult> ListAttachments(HttpContext ctx, string id, RequestWorkflow workflow, CancellationToken ct)
    {
        var result = await workflow.GetAsync(ctx.User.ToAppUser(), id, ct);
        return result.IsSuccess ? TypedResults.Ok(result.Value!.Attachments) : Problem(result.Error!);
    }

    private static async Task<IResult> UploadAttachment(
        HttpContext ctx, string id, IFormFile file, RequestWorkflow workflow, RequestHubDbContext db,
        IAttachmentStore store, StorageSettings settings, TimeProvider clock, CancellationToken ct)
    {
        var user = ctx.User.ToAppUser();
        var access = await workflow.GetAccessibleAsync(user, id, forUpload: true, ct);
        if (!access.IsSuccess) return Problem(access.Error!);
        var request = access.Value!;

        if (file.Length == 0 || file.Length > settings.MaxBytes)
        {
            return Problem(WorkflowError.Validation($"Files must be between 1 byte and {settings.MaxBytes / (1024 * 1024)} MB."));
        }

        if (request.Attachments.Count >= settings.MaxPerRequest)
        {
            return Problem(WorkflowError.Validation($"A request can have at most {settings.MaxPerRequest} attachments."));
        }

        await using var buffer = new MemoryStream();
        await file.CopyToAsync(buffer, ct);
        var bytes = buffer.ToArray();
        var fileName = AttachmentPolicy.SafeFileName(file.FileName);
        var (contentType, error) = AttachmentPolicy.Check(fileName, bytes.AsSpan(0, Math.Min(bytes.Length, 512)));
        if (error is not null) return Problem(new WorkflowError("attachment.type_not_allowed", error, 415));

        var attachment = new AttachmentMetadata
        {
            Id = Guid.NewGuid(),
            RequestId = request.Id,
            FileName = fileName,
            ContentType = contentType!,
            SizeBytes = bytes.Length,
            StorageKey = $"{request.PublicId}/{Guid.NewGuid():N}",
            Sha256 = Convert.ToHexStringLower(SHA256.HashData(bytes)),
            UploadedById = user.Id,
            UploadedAt = clock.GetUtcNow(),
        };
        await store.SaveAsync(attachment.StorageKey, new MemoryStream(bytes), attachment.ContentType, ct);
        db.Attachments.Add(attachment);
        workflow.RecordAudit(request.Id, user.Id, "attachment.added", new { request = request.PublicId, file = fileName, size = bytes.Length, sha256 = attachment.Sha256 });
        await workflow.SaveAsync(ct);

        return TypedResults.Created($"/api/requests/{request.PublicId}/attachments/{attachment.Id}/content", new AttachmentDto(
            attachment.Id, fileName, attachment.ContentType, attachment.SizeBytes, attachment.Sha256, new PersonRef(user.Id, user.DisplayName),
            attachment.UploadedAt, $"/api/requests/{request.PublicId}/attachments/{attachment.Id}/content"));
    }

    private static async Task<IResult> DownloadAttachment(HttpContext ctx, string id, Guid attachmentId, RequestWorkflow workflow, IAttachmentStore store, CancellationToken ct)
    {
        var access = await workflow.GetAccessibleAsync(ctx.User.ToAppUser(), id, forUpload: false, ct);
        if (!access.IsSuccess) return Problem(access.Error!);
        var attachment = access.Value!.Attachments.FirstOrDefault(a => a.Id == attachmentId);
        if (attachment is null) return Problem(new WorkflowError("attachment.not_found", "Attachment not found.", 404));
        var stream = await store.OpenAsync(attachment.StorageKey, ct);
        if (stream is null) return Problem(new WorkflowError("attachment.content_missing", "Attachment content is unavailable.", 404));
        return TypedResults.File(stream, attachment.ContentType, attachment.FileName);
    }

    private static async Task<IResult> Recommend(HttpContext ctx, string id, RequestWorkflow workflow, CancellationToken ct)
    {
        var result = await workflow.RecommendAsync(ctx.User.ToAppUser(), id, ct);
        return result.IsSuccess ? TypedResults.Created($"/api/requests/{id}/triage-recommendations", result.Value) : Problem(result.Error!);
    }

    private static async Task<IResult> ListRecommendations(HttpContext ctx, string id, RequestWorkflow workflow, CancellationToken ct)
    {
        var result = await workflow.ListRecommendationsAsync(ctx.User.ToAppUser(), id, ct);
        return result.IsSuccess ? TypedResults.Ok(result.Value) : Problem(result.Error!);
    }

    private static async Task<IResult> ConfirmRecommendation(HttpContext ctx, string id, Guid recommendationId, RequestWorkflow workflow, CancellationToken ct)
    {
        var result = await workflow.ConfirmRecommendationAsync(ctx.User.ToAppUser(), id, recommendationId, ct);
        return result.IsSuccess ? TypedResults.Ok(result.Value) : Problem(result.Error!);
    }

    private static async Task<IResult> ResetDemo(HttpContext ctx, IConfiguration config, DemoSeeder seeder, ILoggerFactory logs, CancellationToken ct)
    {
        if (!config.GetValue<bool>("Demo:AllowReset"))
        {
            return Problem(new WorkflowError("demo.reset_disabled", "Demo reset is disabled in this environment (Demo:AllowReset=false).", 403));
        }

        var industry = config["Demo:Industry"];
        await seeder.ResetAsync(industry, ct);
        logs.CreateLogger("RequestHub.Admin").LogWarning("Demo data reset by {UserId} (industry {Industry})", ctx.User.ToAppUser().Id, industry ?? "general");
        return TypedResults.Ok(new { reset = true, industry = industry ?? "general", requests = DemoSeeder.SeedRequestCount });
    }

    private static async Task<Ok<BacklogSnapshot>> Backlog(NotificationProcessor processor, CancellationToken ct) =>
        TypedResults.Ok(await processor.GetBacklogAsync(ct));

    private static MeDto ToMe(AppUser user) => new(user.Id, user.DisplayName, [.. user.Roles.Order()], [.. user.Departments.Order()], user.HomeDepartmentId);

    internal static IResult Problem(WorkflowError error)
    {
        var extensions = new Dictionary<string, object?> { ["code"] = error.Code };
        if (error.Extensions is not null)
        {
            foreach (var prop in error.Extensions.GetType().GetProperties())
            {
                extensions[prop.Name] = prop.GetValue(error.Extensions);
            }
        }

        return TypedResults.Problem(detail: error.Message, statusCode: error.Status, title: error.Code, extensions: extensions);
    }
}
