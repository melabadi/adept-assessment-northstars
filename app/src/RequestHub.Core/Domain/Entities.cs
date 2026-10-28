namespace RequestHub.Core.Domain;

public enum RequestStatus { Submitted, InReview, Approved, Rejected }

public enum RequestPriority { Low, Normal, High, Urgent }

public enum DecisionOutcome { Approved, Rejected }

public enum NotificationStatus { Pending, Sent, Failed }

public enum RecommendationStatus { Proposed, Superseded, Confirmed }

/// <summary>Application roles. A user can hold several.</summary>
public static class Roles
{
    public const string Requester = "Requester";
    public const string Reviewer = "Reviewer";
    public const string Approver = "Approver";
    public const string Admin = "Admin";

    public static readonly string[] All = [Requester, Reviewer, Approver, Admin];
}

public static class RequestStatusExtensions
{
    public static bool IsTerminal(this RequestStatus status) =>
        status is RequestStatus.Approved or RequestStatus.Rejected;
}

public sealed class Department
{
    public required string Id { get; set; }
    public required string NameEn { get; set; }
    public required string NameFr { get; set; }
}

public sealed class User
{
    public required string Id { get; set; }
    public required string DisplayName { get; set; }
    public string? Email { get; set; }
    public required string HomeDepartmentId { get; set; }
    public List<string> Roles { get; set; } = [];
    /// <summary>Departments whose queue this user may see and act on (reviewers, approvers).</summary>
    public List<string> DepartmentAccess { get; set; } = [];
    /// <summary>True for seeded demo personas. Synthetic users can only sign in with the local development login.</summary>
    public bool IsSynthetic { get; set; }
    /// <summary>Identity-provider object id (Entra oid) for real principals.</summary>
    public string? ExternalId { get; set; }
}

public sealed class Request
{
    public Guid Id { get; set; }
    /// <summary>Public sequence number; the public id is REQ-{Number}.</summary>
    public int Number { get; set; }
    public string PublicId => FormatPublicId(Number);
    public required string Title { get; set; }
    public required string Description { get; set; }
    public required string Category { get; set; }
    public required string DepartmentId { get; set; }
    public RequestPriority Priority { get; set; } = RequestPriority.Normal;
    public RequestStatus Status { get; set; } = RequestStatus.Submitted;
    public required string RequesterId { get; set; }
    public User? Requester { get; set; }
    public string? IdempotencyKey { get; set; }
    public DateTimeOffset CreatedAt { get; set; }
    public DateTimeOffset UpdatedAt { get; set; }
    /// <summary>Optimistic concurrency token (PostgreSQL xmin).</summary>
    public uint Version { get; set; }

    public ApprovalDecision? Decision { get; set; }
    public List<Comment> Comments { get; set; } = [];
    public List<AttachmentMetadata> Attachments { get; set; } = [];
    public List<TriageRecommendation> Recommendations { get; set; } = [];

    public static string FormatPublicId(int number) => $"REQ-{number}";

    public static bool TryParsePublicId(string value, out int number)
    {
        number = 0;
        return value.StartsWith("REQ-", StringComparison.OrdinalIgnoreCase)
            && int.TryParse(value.AsSpan(4), out number) && number > 0;
    }
}

public sealed class ApprovalDecision
{
    public Guid Id { get; set; }
    public Guid RequestId { get; set; }
    public DecisionOutcome Outcome { get; set; }
    public required string DecidedById { get; set; }
    public User? DecidedBy { get; set; }
    public string? Comment { get; set; }
    public string? IdempotencyKey { get; set; }
    public DateTimeOffset DecidedAt { get; set; }
}

public sealed class Comment
{
    public Guid Id { get; set; }
    public Guid RequestId { get; set; }
    public required string AuthorId { get; set; }
    public User? Author { get; set; }
    /// <summary>Plain text only. Never rendered as HTML.</summary>
    public required string Body { get; set; }
    public DateTimeOffset CreatedAt { get; set; }
}

public sealed class AttachmentMetadata
{
    public Guid Id { get; set; }
    public Guid RequestId { get; set; }
    public required string FileName { get; set; }
    public required string ContentType { get; set; }
    public long SizeBytes { get; set; }
    public required string StorageKey { get; set; }
    public required string Sha256 { get; set; }
    public required string UploadedById { get; set; }
    public DateTimeOffset UploadedAt { get; set; }
}

public sealed class AuditEvent
{
    public long Id { get; set; }
    public Guid? RequestId { get; set; }
    public required string Actor { get; set; }
    public required string Action { get; set; }
    /// <summary>JSON document with action-specific details.</summary>
    public string Details { get; set; } = "{}";
    public string? CorrelationId { get; set; }
    public DateTimeOffset OccurredAt { get; set; }
}

public sealed class Notification
{
    public Guid Id { get; set; }
    public Guid? RequestId { get; set; }
    public required string Recipient { get; set; }
    public required string Type { get; set; }
    public string Payload { get; set; } = "{}";
    public NotificationStatus Status { get; set; } = NotificationStatus.Pending;
    public int Attempts { get; set; }
    public DateTimeOffset NextAttemptAt { get; set; }
    public DateTimeOffset CreatedAt { get; set; }
    public DateTimeOffset? ProcessedAt { get; set; }
    public string? LastError { get; set; }
    public string? CorrelationId { get; set; }
}

public sealed class TriageRecommendation
{
    public Guid Id { get; set; }
    /// <summary>Optimistic concurrency token (PostgreSQL xmin).</summary>
    public uint Version { get; set; }
    public Guid RequestId { get; set; }
    /// <summary>Provider id, e.g. "sample-rules" or "foundry-agent".</summary>
    public required string Provider { get; set; }
    /// <summary>True when produced by deterministic sample rules rather than an AI service.</summary>
    public bool IsSample { get; set; }
    public required string SuggestedDepartmentId { get; set; }
    public RequestPriority SuggestedPriority { get; set; }
    public required string Rationale { get; set; }
    /// <summary>Policy references formatted as "POLICY-ID@version".</summary>
    public List<string> PolicyRefs { get; set; } = [];
    public double Confidence { get; set; }
    public bool NeedsHumanReview { get; set; }
    public RecommendationStatus Status { get; set; } = RecommendationStatus.Proposed;
    /// <summary>The department the request was routed to when the recommendation was produced.</summary>
    public required string DepartmentAtRecommendation { get; set; }
    public required string CreatedById { get; set; }
    public DateTimeOffset CreatedAt { get; set; }
    /// <summary>Provider trace/response id for live AI providers (evidence of a real call).</summary>
    public string? ProviderTraceId { get; set; }
}
