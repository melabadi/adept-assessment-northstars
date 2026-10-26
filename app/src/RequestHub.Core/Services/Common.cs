using System.Diagnostics;
using System.Diagnostics.Metrics;
using RequestHub.Core.Domain;

namespace RequestHub.Core.Services;

/// <summary>The authenticated caller, resolved from the identity provider and the Users table.</summary>
public sealed record AppUser(
    string Id,
    string DisplayName,
    IReadOnlySet<string> Roles,
    IReadOnlySet<string> Departments,
    string HomeDepartmentId)
{
    public bool HasRole(string role) => Roles.Contains(role);

    public bool IsAdmin => Roles.Contains(Domain.Roles.Admin);

    public bool CanAccessDepartment(string departmentId) => IsAdmin || Departments.Contains(departmentId);

    public bool IsStaffFor(string departmentId) =>
        (HasRole(Domain.Roles.Reviewer) || HasRole(Domain.Roles.Approver) || IsAdmin) && CanAccessDepartment(departmentId);
}

/// <summary>A business-rule failure mapped to an RFC 7807 problem response by the API.</summary>
public sealed record WorkflowError(string Code, string Message, int Status, object? Extensions = null)
{
    public static WorkflowError NotFound(string id) => new("request.not_found", $"Request {id} was not found.", 404);
    public static WorkflowError Forbidden(string message) => new("auth.department_forbidden", message, 403);
    public static WorkflowError Validation(string message) => new("validation.failed", message, 400);
}

public sealed class Result<T>
{
    public T? Value { get; private init; }
    public WorkflowError? Error { get; private init; }
    /// <summary>True when an idempotent retry returned the original outcome.</summary>
    public bool Replayed { get; private init; }
    public bool IsSuccess => Error is null;

    public static Result<T> Ok(T value, bool replayed = false) => new() { Value = value, Replayed = replayed };
    public static Result<T> Fail(WorkflowError error) => new() { Error = error };
    public static implicit operator Result<T>(WorkflowError error) => Fail(error);
}

public static class RequestHubTelemetry
{
    public const string SourceName = "RequestHub";
    public static readonly ActivitySource ActivitySource = new(SourceName);
    public static readonly Meter Meter = new(SourceName);

    public static readonly Counter<long> RequestsCreated = Meter.CreateCounter<long>("requesthub.requests.created");
    public static readonly Counter<long> DecisionsRecorded = Meter.CreateCounter<long>("requesthub.decisions.recorded");
    public static readonly Counter<long> DecisionConflicts = Meter.CreateCounter<long>("requesthub.decisions.conflicts");
    public static readonly Counter<long> TriageCalls = Meter.CreateCounter<long>("requesthub.triage.calls");
    public static readonly Counter<long> NotificationsProcessed = Meter.CreateCounter<long>("requesthub.notifications.processed");
    public static readonly Histogram<double> TriageDuration = Meter.CreateHistogram<double>("requesthub.triage.duration", unit: "ms");

    public static string? CorrelationId => Activity.Current?.TraceId.ToString();
}

/// <summary>
/// Opt-in fault injection for the Test, Release, and Operate demos. Every fault requires an expiry
/// timestamp and switches itself off afterwards, even if a demo session is interrupted.
/// </summary>
public sealed class FaultOptions
{
    public const string Section = "Faults";

    /// <summary>Extra delay per notification in the worker (Operate demo: worker backlog).</summary>
    public int WorkerDelayMs { get; set; }
    /// <summary>Extra delay on the queue/list endpoint (Test demo: slow query).</summary>
    public int QueueDelayMs { get; set; }
    /// <summary>Readiness probe fails (Release demo: bad revision).</summary>
    public bool FailReadiness { get; set; }
    /// <summary>UTC time after which all faults are ignored. Faults without an expiry are never active.</summary>
    public DateTimeOffset? ExpiresAtUtc { get; set; }

    public bool IsActive(TimeProvider clock) => ExpiresAtUtc is { } expiry && clock.GetUtcNow() < expiry;
}

public static class EnumText
{
    public static string Of(RequestStatus s) => s.ToString();
    public static string Of(RequestPriority p) => p.ToString();
}
