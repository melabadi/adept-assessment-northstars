using RequestHub.Core.Profiles;

namespace RequestHub.Core.Triage;

/// <summary>
/// Extension point for triage recommendations. A provider proposes routing; it never approves or rejects.
/// The base app ships <see cref="SampleRulesTriageProvider"/>. Live AI providers (for example FoundryTriageProvider,
/// which calls a Microsoft Foundry agent) implement this interface and are selected with the Triage:Provider setting.
/// </summary>
public interface ITriageProvider
{
    /// <summary>Stable provider id stored with each recommendation, e.g. "sample-rules" or "foundry-agent".</summary>
    string Id { get; }

    /// <summary>True when the provider is deterministic sample logic rather than an AI service.</summary>
    bool IsSample { get; }

    Task<TriageResult> RecommendAsync(TriageContext context, CancellationToken cancellationToken);
}

/// <summary>Permitted request context handed to a provider. Contains no data the caller cannot already see.</summary>
public sealed record TriageContext(
    string RequestId,
    string Title,
    string Description,
    string Category,
    string CurrentDepartmentId,
    string CurrentPriority,
    IReadOnlyList<RoutingPolicy> Policies,
    IReadOnlyList<TriageDepartment> Departments,
    ITriageTools Tools);

public sealed record TriageDepartment(string Id, string Name);

/// <summary>Narrowly scoped, audited tools a live agent may call. Implementations enforce the caller's access.</summary>
public interface ITriageTools
{
    /// <summary>Returns permitted fields of a request, or an error object when the caller may not read it.</summary>
    Task<string> GetRequestAsync(string requestId, CancellationToken cancellationToken);

    /// <summary>Returns the approved routing policies, optionally filtered by category.</summary>
    Task<string> GetRoutingPoliciesAsync(string? category, CancellationToken cancellationToken);
}

public sealed record TriageResult(
    string SuggestedDepartmentId,
    string SuggestedPriority,
    string Rationale,
    IReadOnlyList<string> PolicyIds,
    double Confidence,
    bool NeedsHumanReview,
    string? ClarifyingQuestion = null,
    string? ProviderTraceId = null);

/// <summary>The provider is not configured or the service could not be reached.</summary>
public sealed class TriageUnavailableException(string message, Exception? inner = null) : Exception(message, inner);

/// <summary>The provider returned output that failed schema or policy validation.</summary>
public sealed class TriageInvalidOutputException(string message) : Exception(message);
