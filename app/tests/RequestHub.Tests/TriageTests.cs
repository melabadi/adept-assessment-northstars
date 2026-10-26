using System.Net;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.DependencyInjection.Extensions;
using RequestHub.Core.Data;
using RequestHub.Core.Services;
using RequestHub.Core.Triage;

namespace RequestHub.Tests;

public sealed class TriageTests(ApiFixture api) : IClassFixture<ApiFixture>
{
    [Fact]
    public async Task Sample_recommendation_is_labelled_cites_a_policy_and_changes_nothing()
    {
        var before = await (await api.As("u-ben").GetAsync("/api/requests/REQ-1001")).Read<RequestDetailDto>();
        var response = await api.As("u-ben").PostAsync("/api/requests/REQ-1001/triage-recommendations", null);
        Assert.Equal(HttpStatusCode.Created, response.StatusCode);
        var rec = await response.Read<RecommendationDto>();
        Assert.True(rec.IsSample);
        Assert.Equal("sample-rules", rec.Provider);
        Assert.Equal("IT", rec.SuggestedDepartmentId);
        Assert.Contains(rec.PolicyRefs, p => p.PolicyId == "POL-ROUTE-001" && p.Version == "1.2");

        var after = await (await api.As("u-ben").GetAsync("/api/requests/REQ-1001")).Read<RequestDetailDto>();
        Assert.Equal(before.Status, after.Status);
        Assert.Equal(before.DepartmentId, after.DepartmentId);
        Assert.Null(after.Decision);
    }

    [Fact]
    public async Task Conflicting_policies_are_flagged_for_human_review()
    {
        var rec = await (await api.As("u-ben").PostAsync("/api/requests/REQ-1012/triage-recommendations", null)).Read<RecommendationDto>();
        Assert.True(rec.NeedsHumanReview);
        Assert.Contains(rec.PolicyRefs, p => p.PolicyId == "POL-ROUTE-004");
    }

    [Fact]
    public async Task Requesters_cannot_request_triage()
    {
        var response = await api.As("u-ava").PostAsync("/api/requests/REQ-1001/triage-recommendations", null);
        Assert.Equal(HttpStatusCode.Forbidden, response.StatusCode);
    }

    [Fact]
    public async Task Policies_endpoint_lists_versioned_policies()
    {
        var policies = await (await api.As("u-ben").GetAsync("/api/policies")).Read<List<PolicyDto>>();
        Assert.Contains(policies, p => p.Id == "POL-GOV-001");
        Assert.All(policies, p => Assert.False(string.IsNullOrWhiteSpace(p.Version)));
    }
}

/// <summary>A provider that misbehaves on purpose, to prove the app's guards (not the model) decide what is accepted.</summary>
public sealed class MisbehavingTriageProvider : ITriageProvider
{
    public static string Mode { get; set; } = "approval-claim";

    public string Id => "test-misbehaving";

    public bool IsSample => false;

    public async Task<TriageResult> RecommendAsync(TriageContext context, CancellationToken cancellationToken)
    {
        switch (Mode)
        {
            case "approval-claim":
                return new TriageResult("IT", "Normal", "This request is approved and can proceed.", ["POL-ROUTE-001"], 0.9, false);
            case "unknown-policy":
                return new TriageResult("IT", "Normal", "Routing by an invented rule.", ["POL-MADE-UP-9"], 0.9, false);
            case "conflict-unflagged":
                return new TriageResult("FIN", "Normal", "The spend threshold applies.", ["POL-ROUTE-001", "POL-ROUTE-004"], 0.9, false);
            case "below-threshold-citation":
                return new TriageResult("IT", "Normal", "Software routes to IT; the cost is below the spend threshold.", ["POL-ROUTE-002", "POL-ROUTE-004"], 0.9, false);
            case "cross-request":
                var other = await context.Tools.GetRequestAsync("REQ-1006", cancellationToken);
                var own = await context.Tools.GetRequestAsync(context.RequestId, cancellationToken);
                Assert.Contains("not_permitted", other);
                Assert.Contains(context.Title, own);
                // Data minimization: comments and people data never reach the AI service.
                Assert.DoesNotContain("comments", own);
                Assert.DoesNotContain("requester", own, StringComparison.OrdinalIgnoreCase);
                return new TriageResult("IT", "Normal", "Read only the permitted request.", ["POL-ROUTE-001"], 0.8, false);
            case "slow":
                await Task.Delay(TimeSpan.FromSeconds(30), cancellationToken);
                throw new InvalidOperationException("unreachable");
            default:
                throw new TriageUnavailableException("Provider offline.");
        }
    }
}

public sealed class GuardedTriageFixture : ApiFixture
{
    protected override void ConfigureTestServices(IServiceCollection services)
    {
        services.RemoveAll<ITriageProvider>();
        services.AddSingleton<ITriageProvider, MisbehavingTriageProvider>();
        services.Configure<TriageOptions>(o => o.TimeoutSeconds = 2);
    }
}

public sealed class TriageGuardTests(GuardedTriageFixture api) : IClassFixture<GuardedTriageFixture>
{
    [Fact]
    public async Task Recommendation_claiming_approval_is_rejected()
    {
        MisbehavingTriageProvider.Mode = "approval-claim";
        var response = await api.As("u-ben").PostAsync("/api/requests/REQ-1002/triage-recommendations", null);
        Assert.Equal(HttpStatusCode.BadGateway, response.StatusCode);
        Assert.Equal("triage.invalid_output", await response.Code());
    }

    [Fact]
    public async Task Recommendation_citing_unknown_policy_is_rejected()
    {
        MisbehavingTriageProvider.Mode = "unknown-policy";
        var response = await api.As("u-ben").PostAsync("/api/requests/REQ-1002/triage-recommendations", null);
        Assert.Equal(HttpStatusCode.BadGateway, response.StatusCode);
    }

    [Fact]
    public async Task Conflicting_citations_are_escalated_even_when_the_provider_does_not_flag_them()
    {
        MisbehavingTriageProvider.Mode = "conflict-unflagged";
        var response = await api.As("u-ben").PostAsync("/api/requests/REQ-1012/triage-recommendations", null);
        Assert.Equal(HttpStatusCode.Created, response.StatusCode);
        var rec = await response.Read<RecommendationDto>();
        Assert.True(rec.NeedsHumanReview);
        Assert.Contains("human review required", rec.Rationale);
    }

    [Fact]
    public async Task Citing_the_spend_policy_below_its_threshold_is_not_a_conflict()
    {
        MisbehavingTriageProvider.Mode = "below-threshold-citation";
        var rec = await (await api.As("u-ben").PostAsync("/api/requests/REQ-1005/triage-recommendations", null)).Read<RecommendationDto>();
        Assert.False(rec.NeedsHumanReview);
    }

    [Fact]
    public async Task Tools_only_expose_the_request_being_triaged_and_are_audited()
    {
        MisbehavingTriageProvider.Mode = "cross-request";
        var response = await api.As("u-ben").PostAsync("/api/requests/REQ-1014/triage-recommendations", null);
        Assert.Equal(HttpStatusCode.Created, response.StatusCode);

        await using var scope = api.Factory.Services.CreateAsyncScope();
        var db = scope.ServiceProvider.GetRequiredService<RequestHubDbContext>();
        var toolCalls = await db.AuditEvents.Where(a => a.Action == "triage.tool_call").Select(a => a.Details).ToListAsync();
        Assert.Contains(toolCalls, d => d.Contains("denied") && d.Contains("REQ-1006"));
        Assert.Contains(toolCalls, d => d.Contains("\"ok\"") && d.Contains("REQ-1014"));
    }

    [Fact]
    public async Task Slow_provider_times_out_with_clear_error()
    {
        MisbehavingTriageProvider.Mode = "slow";
        var response = await api.As("u-ben").PostAsync("/api/requests/REQ-1002/triage-recommendations", null);
        Assert.Equal(HttpStatusCode.GatewayTimeout, response.StatusCode);
        Assert.Equal("triage.timeout", await response.Code());
    }

    [Fact]
    public async Task Unavailable_provider_returns_service_unavailable()
    {
        MisbehavingTriageProvider.Mode = "offline";
        var response = await api.As("u-ben").PostAsync("/api/requests/REQ-1002/triage-recommendations", null);
        Assert.Equal(HttpStatusCode.ServiceUnavailable, response.StatusCode);
        Assert.Equal("triage.unavailable", await response.Code());
    }
}

public sealed class FoundryOutputParsingTests
{
    private const string Answer = """{"suggestedDepartmentId":"FIN","suggestedPriority":"Normal","rationale":"r","policyIds":["POL-ROUTE-007"],"confidence":0.6,"needsHumanReview":true,"clarifyingQuestion":"q"}""";

    [Fact]
    public void Single_answer_is_parsed()
    {
        var output = RequestHub.Api.Triage.FoundryTriageProvider.ParseOutput(Answer, out var answers);
        Assert.Equal(1, answers);
        Assert.Equal("FIN", output!.SuggestedDepartmentId);
    }

    [Fact]
    public void Repeated_answer_uses_the_last_object()
    {
        var output = RequestHub.Api.Triage.FoundryTriageProvider.ParseOutput(Answer.Replace("FIN", "HR", StringComparison.Ordinal) + Answer, out var answers);
        Assert.Equal(2, answers);
        Assert.Equal("FIN", output!.SuggestedDepartmentId);
    }

    [Fact]
    public void Non_json_text_is_rejected() =>
        Assert.ThrowsAny<System.Text.Json.JsonException>(() => RequestHub.Api.Triage.FoundryTriageProvider.ParseOutput("Routing: IT", out _));
}
