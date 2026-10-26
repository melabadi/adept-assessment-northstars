using System.Text.Json;
using Microsoft.EntityFrameworkCore;
using RequestHub.Core.Data;
using RequestHub.Core.Domain;
using RequestHub.Core.Profiles;

namespace RequestHub.Core.Services;

/// <summary>
/// Seeds deterministic synthetic demo data: 5 departments, 8 personas, 24 requests (REQ-1001..REQ-1024).
/// REQ-1001 is always an equipment request awaiting triage. All people and data are fictional.
/// </summary>
public sealed class DemoSeeder(RequestHubDbContext db, TimeProvider clock)
{
    public const int SeedRequestCount = 24;

    public static readonly IReadOnlyList<User> Personas =
    [
        Persona("u-ava", "Ava Martin", "OPS", [Roles.Requester], []),
        Persona("u-ben", "Ben Okafor", "IT", [Roles.Requester, Roles.Reviewer], ["IT", "FAC"]),
        Persona("u-chloe", "Chloé Dubois", "IT", [Roles.Requester, Roles.Approver], ["IT", "FAC"]),
        Persona("u-dan", "Dan Rivera", "OPS", [Roles.Requester, Roles.Reviewer, Roles.Approver, Roles.Admin], ["IT", "FAC", "FIN", "HR", "OPS"]),
        Persona("u-eli", "Eli Novak", "FIN", [Roles.Requester], []),
        Persona("u-fatima", "Fatima Haddad", "HR", [Roles.Requester], []),
        Persona("u-grace", "Grace Liu", "FIN", [Roles.Requester, Roles.Reviewer, Roles.Approver], ["FIN", "HR"]),
        Persona("u-hugo", "Hugo Bernard", "IT", [Roles.Requester, Roles.Approver], ["IT"]),
    ];

    // Deterministic patterns used when a profile supplies templates instead of 24 explicit requests.
    private static readonly string[] StatusPattern =
    [
        "Submitted", "Submitted", "InReview", "Approved", "Submitted", "Rejected", "InReview", "Approved",
        "Submitted", "InReview", "Approved", "Submitted", "Rejected", "Submitted", "InReview", "Approved",
        "Submitted", "Submitted", "InReview", "Approved", "Rejected", "Submitted", "InReview", "Submitted",
    ];

    private static readonly string[] RequesterPattern = ["u-ava", "u-eli", "u-fatima", "u-hugo"];

    public async Task<bool> SeedIfEmptyAsync(string? industry, CancellationToken ct = default)
    {
        if (await db.Requests.AnyAsync(ct))
        {
            return false;
        }

        await SeedAsync(ProfileCatalog.Load(industry), ct);
        return true;
    }

    /// <summary>Deletes all business data in this database and reseeds it. Scoped to the configured demo database only.</summary>
    public async Task ResetAsync(string? industry, CancellationToken ct = default)
    {
        var profile = ProfileCatalog.Load(industry);
        await using var tx = await db.Database.BeginTransactionAsync(ct);
        await db.Database.ExecuteSqlRawAsync(
            "TRUNCATE TABLE \"Notifications\", \"AuditEvents\", \"Recommendations\", \"Attachments\", \"Comments\", \"Decisions\", \"Requests\", \"Users\", \"Departments\" RESTART IDENTITY CASCADE",
            ct);
        db.ChangeTracker.Clear();
        await SeedCoreAsync(profile, ct);
        await tx.CommitAsync(ct);
    }

    private async Task SeedAsync(IndustryProfile profile, CancellationToken ct)
    {
        await using var tx = await db.Database.BeginTransactionAsync(ct);
        await SeedCoreAsync(profile, ct);
        await tx.CommitAsync(ct);
    }

    private async Task SeedCoreAsync(IndustryProfile profile, CancellationToken ct)
    {
        var now = clock.GetUtcNow();

        db.Departments.AddRange(profile.Departments.Select(d => new Department { Id = d.Id, NameEn = d.En, NameFr = d.Fr }));
        db.Users.AddRange(Personas.Select(Clone));
        await db.SaveChangesAsync(ct);

        var seeds = ExpandSeeds(profile);
        for (var i = 0; i < seeds.Count; i++)
        {
            var seed = seeds[i];
            var number = RequestHubDbContext.FirstRequestNumber + i;
            var created = now.AddHours(-(seed.AgeHours ?? (6 + i * 7)));
            var status = Enum.Parse<RequestStatus>(seed.Status ?? StatusPattern[i % StatusPattern.Length]);
            var requesterId = seed.Requester ?? RequesterPattern[i % RequesterPattern.Length];

            var request = new Request
            {
                Id = DeterministicGuid("request", number),
                Number = number,
                Title = seed.Title,
                Description = seed.Description,
                Category = seed.Category,
                DepartmentId = seed.Department,
                Priority = Enum.Parse<RequestPriority>(seed.Priority),
                Status = status,
                RequesterId = requesterId,
                CreatedAt = created,
                UpdatedAt = created,
            };
            db.Requests.Add(request);
            db.AuditEvents.Add(Audit(request.Id, requesterId, "request.created", created, new { request = request.PublicId, seeded = true }));

            var commentTime = created.AddMinutes(45);
            foreach (var comment in seed.Comments)
            {
                db.Comments.Add(new Comment
                {
                    Id = Guid.NewGuid(),
                    RequestId = request.Id,
                    AuthorId = comment.Author,
                    Body = comment.Body,
                    CreatedAt = commentTime,
                });
                db.AuditEvents.Add(Audit(request.Id, comment.Author, "comment.added", commentTime, new { request = request.PublicId }));
                commentTime = commentTime.AddMinutes(30);
            }

            if (seed.Recommendation is { } rec)
            {
                var refs = rec.Policies.Select(id => profile.FindPolicy(id)?.Ref ?? id).ToList();
                db.Recommendations.Add(new TriageRecommendation
                {
                    Id = Guid.NewGuid(),
                    RequestId = request.Id,
                    Provider = "sample-rules",
                    IsSample = true,
                    SuggestedDepartmentId = rec.Department,
                    SuggestedPriority = Enum.Parse<RequestPriority>(rec.Priority),
                    Rationale = rec.Rationale,
                    PolicyRefs = refs,
                    Confidence = 0.6,
                    DepartmentAtRecommendation = seed.Department,
                    CreatedById = "u-ben",
                    CreatedAt = created.AddMinutes(20),
                });
                db.AuditEvents.Add(Audit(request.Id, "u-ben", "triage.recommended", created.AddMinutes(20), new { request = request.PublicId, provider = "sample-rules" }));
            }

            if (status.IsTerminal())
            {
                var decision = seed.Decision ?? DefaultDecision(status, seed.Department);
                var decidedAt = created.AddHours(4);
                db.Decisions.Add(new ApprovalDecision
                {
                    Id = DeterministicGuid("decision", number),
                    RequestId = request.Id,
                    Outcome = Enum.Parse<DecisionOutcome>(decision.Outcome),
                    DecidedById = decision.By,
                    Comment = decision.Comment,
                    DecidedAt = decidedAt,
                });
                request.UpdatedAt = decidedAt;
                db.AuditEvents.Add(Audit(request.Id, decision.By, "decision.recorded", decidedAt, new { request = request.PublicId, outcome = decision.Outcome }));
                db.Notifications.Add(new Notification
                {
                    Id = Guid.NewGuid(),
                    RequestId = request.Id,
                    Recipient = requesterId,
                    Type = "request.decided",
                    Payload = JsonSerializer.Serialize(new { request = request.PublicId, outcome = decision.Outcome }),
                    Status = NotificationStatus.Sent,
                    Attempts = 1,
                    CreatedAt = decidedAt,
                    NextAttemptAt = decidedAt,
                    ProcessedAt = decidedAt.AddSeconds(2),
                });
            }
        }

        await db.SaveChangesAsync(ct);
        var nextNumber = RequestHubDbContext.FirstRequestNumber + seeds.Count;
        await db.Database.ExecuteSqlAsync($"SELECT setval('\"RequestNumbers\"', {nextNumber}, false)", ct);
    }

    private static List<SeedRequest> ExpandSeeds(IndustryProfile profile)
    {
        if (profile.Requests.Count >= SeedRequestCount)
        {
            return profile.Requests.Take(SeedRequestCount).ToList();
        }

        // Templates are cycled across sites to produce 24 deterministic requests.
        var templates = profile.Requests;
        var sites = profile.Sites.Count > 0 ? profile.Sites : ["Main site"];
        var result = new List<SeedRequest>(SeedRequestCount);
        for (var i = 0; i < SeedRequestCount; i++)
        {
            var t = templates[i % templates.Count];
            var site = sites[(i / templates.Count) % sites.Count];
            result.Add(new SeedRequest
            {
                Title = i < templates.Count ? t.Title : $"{t.Title} ({site})",
                Description = t.Description,
                Category = t.Category,
                Department = t.Department,
                Priority = i == 0 ? "Normal" : t.Priority,
                Status = i == 0 ? "Submitted" : null,
                Requester = i == 0 ? "u-ava" : null,
                AgeHours = i == 0 ? 6 : null,
            });
        }

        return result;
    }

    private static SeedDecision DefaultDecision(RequestStatus status, string department)
    {
        var approver = department is "FIN" or "HR" ? "u-grace" : "u-chloe";
        return status == RequestStatus.Approved
            ? new SeedDecision("Approved", approver, "Approved per policy.")
            : new SeedDecision("Rejected", approver, "Rejected: outside current policy.");
    }

    private static AuditEvent Audit(Guid requestId, string actor, string action, DateTimeOffset at, object details) => new()
    {
        RequestId = requestId,
        Actor = actor,
        Action = action,
        Details = JsonSerializer.Serialize(details),
        OccurredAt = at,
    };

    private static Guid DeterministicGuid(string kind, int number)
    {
        var bytes = System.Security.Cryptography.MD5.HashData(System.Text.Encoding.UTF8.GetBytes($"requesthub:{kind}:{number}"));
        return new Guid(bytes);
    }

    private static User Persona(string id, string name, string home, string[] roles, string[] access) => new()
    {
        Id = id,
        DisplayName = name,
        Email = $"{id[2..]}@example.com",
        HomeDepartmentId = home,
        Roles = [.. roles],
        DepartmentAccess = [.. access],
        IsSynthetic = true,
    };

    private static User Clone(User u) => new()
    {
        Id = u.Id,
        DisplayName = u.DisplayName,
        Email = u.Email,
        HomeDepartmentId = u.HomeDepartmentId,
        Roles = [.. u.Roles],
        DepartmentAccess = [.. u.DepartmentAccess],
        IsSynthetic = true,
    };
}
