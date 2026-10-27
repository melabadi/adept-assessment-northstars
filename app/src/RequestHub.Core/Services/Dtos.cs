using System.Text.Json;

namespace RequestHub.Core.Services;

// Public API contract (requesthub.v1). Changing these shapes requires a contract review (see contracts/README.md).

public sealed record PersonRef(string Id, string DisplayName);

public sealed record RequestSummaryDto(
    string Id,
    string Title,
    string Category,
    string DepartmentId,
    string Priority,
    string Status,
    PersonRef Requester,
    DateTimeOffset CreatedAt,
    DateTimeOffset UpdatedAt,
    bool HasRecommendation);

public sealed record DecisionDto(string Outcome, PersonRef DecidedBy, string? Comment, DateTimeOffset DecidedAt);

public sealed record CommentDto(Guid Id, PersonRef Author, string Body, DateTimeOffset CreatedAt);

public sealed record AttachmentDto(
    Guid Id,
    string FileName,
    string ContentType,
    long SizeBytes,
    string Sha256,
    PersonRef UploadedBy,
    DateTimeOffset UploadedAt,
    string DownloadUrl);

public sealed record PolicyRefDto(string PolicyId, string Version);

public sealed record RecommendationDto(
    Guid Id,
    string Provider,
    bool IsSample,
    string SuggestedDepartmentId,
    string SuggestedPriority,
    string Rationale,
    IReadOnlyList<PolicyRefDto> PolicyRefs,
    double Confidence,
    bool NeedsHumanReview,
    string Status,
    string DepartmentAtRecommendation,
    PersonRef CreatedBy,
    DateTimeOffset CreatedAt,
    string? ProviderTraceId,
    PersonRef? ConfirmedBy);

public sealed record PermissionsDto(
    bool CanComment,
    bool CanUpload,
    bool CanTriage,
    bool CanRoute,
    bool CanConfirmRecommendation,
    bool CanDecide,
    string? DecideBlockedReason);

public sealed record RequestDetailDto(
    string Id,
    string Title,
    string Description,
    string Category,
    string DepartmentId,
    string Priority,
    string Status,
    PersonRef Requester,
    DateTimeOffset CreatedAt,
    DateTimeOffset UpdatedAt,
    string Version,
    DecisionDto? Decision,
    RecommendationDto? LatestRecommendation,
    IReadOnlyList<CommentDto> Comments,
    IReadOnlyList<AttachmentDto> Attachments,
    PermissionsDto Permissions);

public sealed record AuditEventDto(long Id, string Action, PersonRef Actor, DateTimeOffset OccurredAt, JsonElement Details, string? CorrelationId);

public sealed record PagedResult<T>(IReadOnlyList<T> Items, int Page, int PageSize, int TotalCount, int TotalPages);

public sealed record CreateRequestInput(string Title, string Description, string Category, string DepartmentId, string? Priority);

public sealed record DecisionInput(string Outcome, string? Comment);

public sealed record CommentInput(string Body);

public sealed record RoutingInput(string DepartmentId, string? Reason);

public sealed record RequestQuery(
    string Scope = "queue",
    string? Status = null,
    string? DepartmentId = null,
    string? Priority = null,
    string? Q = null,
    int Page = 1,
    int PageSize = 20);

public sealed record MeDto(
    string Id,
    string DisplayName,
    IReadOnlyList<string> Roles,
    IReadOnlyList<string> Departments,
    string HomeDepartmentId);

public sealed record MetaDto(
    string AppName,
    string AppVersion,
    string BuildSha,
    string Environment,
    string Industry,
    string ContractVersion,
    string TriageProvider,
    string AuthMode,
    string DefaultLocale);

public sealed record DepartmentDto(string Id, string NameEn, string NameFr);

public sealed record CategoryDto(string Id, string NameEn, string NameFr);

public sealed record PolicyDto(
    string Id,
    string Version,
    string Kind,
    string Title,
    string Text,
    string RouteTo,
    string? Priority,
    decimal? Threshold,
    string Ref);

public sealed record PersonaDto(string Id, string DisplayName, IReadOnlyList<string> Roles, IReadOnlyList<string> Departments);

public sealed record ResetInput(string? Industry);
