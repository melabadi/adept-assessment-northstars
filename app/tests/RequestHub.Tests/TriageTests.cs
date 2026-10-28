using System.Net;
using System.Net.Http.Json;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.DependencyInjection.Extensions;
using RequestHub.Core.Data;
using RequestHub.Core.Domain;
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

public sealed class RecommendationConfirmationTests(ApiFixture api) : IClassFixture<ApiFixture>
{
    [Fact]
    public async Task Reviewer_confirmation_routes_to_the_suggestion_without_changing_priority_or_decision_and_records_one_audit()
    {
        var request = await CreateRequestAsync("IT");
        var recommendationId = await AddRecommendationAsync(request.Id, "FAC");

        var response = await ConfirmAsync("u-ben", request.Id, recommendationId);

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var after = await response.Read<RequestDetailDto>();
        Assert.Equal("FAC", after.DepartmentId);
        Assert.Equal("InReview", after.Status);
        Assert.Equal(request.Priority, after.Priority);
        Assert.Null(after.Decision);
        Assert.Equal("Confirmed", after.LatestRecommendation!.Status);

        var history = await (await api.As("u-ava").GetAsync($"/api/requests/{request.Id}/history")).Read<List<AuditEventDto>>();
        var confirmation = Assert.Single(history, e => e.Action == "triage.confirmed");
        Assert.Equal("u-ben", confirmation.Actor.Id);
        Assert.Equal(recommendationId.ToString(), confirmation.Details.GetProperty("recommendationId").GetString());
        Assert.Equal("IT", confirmation.Details.GetProperty("from").GetString());
        Assert.Equal("FAC", confirmation.Details.GetProperty("to").GetString());
        Assert.Equal("sample-rules", confirmation.Details.GetProperty("provider").GetString());
        Assert.Contains(confirmation.Details.GetProperty("policyRefs").EnumerateArray(),
            p => p.GetString() == "POL-ROUTE-003@2.1");
        Assert.DoesNotContain(history, e => e.Action == "routing.changed");

        await using var scope = api.Factory.Services.CreateAsyncScope();
        var db = scope.ServiceProvider.GetRequiredService<RequestHubDbContext>();
        var requestId = await db.Requests.Where(r => r.Number == RequestNumber(request.Id)).Select(r => r.Id).SingleAsync();
        Assert.NotEmpty(await db.Notifications.Where(n => n.RequestId == requestId && n.Type == "request.routed").ToListAsync());
    }

    [Fact]
    public async Task Reviewer_confirmation_for_the_current_department_confirms_without_rerouting()
    {
        var request = await CreateRequestAsync("IT");
        var recommendationId = await AddRecommendationAsync(request.Id, "IT");

        var response = await ConfirmAsync("u-ben", request.Id, recommendationId);

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var after = await response.Read<RequestDetailDto>();
        Assert.Equal("IT", after.DepartmentId);
        Assert.Equal("Submitted", after.Status);
        Assert.Equal("Confirmed", after.LatestRecommendation!.Status);
        var history = await (await api.As("u-ava").GetAsync($"/api/requests/{request.Id}/history")).Read<List<AuditEventDto>>();
        Assert.Single(history, e => e.Action == "triage.confirmed");

        await using var scope = api.Factory.Services.CreateAsyncScope();
        var db = scope.ServiceProvider.GetRequiredService<RequestHubDbContext>();
        var requestId = await db.Requests.Where(r => r.Number == RequestNumber(request.Id)).Select(r => r.Id).SingleAsync();
        Assert.Empty(await db.Notifications.Where(n => n.RequestId == requestId && n.Type == "request.routed").ToListAsync());
    }

    [Fact]
    public async Task Requesters_and_approvers_cannot_confirm_a_recommendation()
    {
        var request = await CreateRequestAsync("IT");
        var recommendationId = await AddRecommendationAsync(request.Id, "FAC");

        foreach (var persona in new[] { "u-ava", "u-chloe" })
        {
            var response = await ConfirmAsync(persona, request.Id, recommendationId);
            Assert.Equal(HttpStatusCode.Forbidden, response.StatusCode);
            Assert.Equal("auth.role_required", await response.Code());
        }
    }

    [Fact]
    public async Task Reviewer_without_access_to_the_current_department_cannot_confirm()
    {
        var request = await CreateRequestAsync("IT");
        var recommendationId = await AddRecommendationAsync(request.Id, "FIN");

        var response = await ConfirmAsync("u-grace", request.Id, recommendationId);

        Assert.Equal(HttpStatusCode.Forbidden, response.StatusCode);
        Assert.Equal("auth.department_forbidden", await response.Code());
    }

    [Fact]
    public async Task Reviewer_without_access_to_the_suggested_department_cannot_confirm()
    {
        var request = await CreateRequestAsync("FAC");
        var recommendationId = await AddRecommendationAsync(request.Id, "FIN");

        var response = await ConfirmAsync("u-ben", request.Id, recommendationId);

        Assert.Equal(HttpStatusCode.Forbidden, response.StatusCode);
        Assert.Equal("auth.department_forbidden", await response.Code());
    }

    [Fact]
    public async Task Superseded_recommendation_cannot_be_confirmed()
    {
        var request = await CreateRequestAsync("IT");
        var recommendationId = await AddRecommendationAsync(request.Id, "FAC", RecommendationStatus.Superseded);

        var response = await ConfirmAsync("u-ben", request.Id, recommendationId);

        Assert.Equal(HttpStatusCode.Conflict, response.StatusCode);
        Assert.Equal("recommendation.stale", await response.Code());
    }

    [Fact]
    public async Task Recommendation_for_a_department_that_has_changed_cannot_be_confirmed()
    {
        var request = await CreateRequestAsync("IT");
        var recommendationId = await AddRecommendationAsync(request.Id, "FAC");
        await SetRequestDepartmentAsync(request.Id, "FAC");

        var response = await ConfirmAsync("u-ben", request.Id, recommendationId);

        Assert.Equal(HttpStatusCode.Conflict, response.StatusCode);
        Assert.Equal("recommendation.stale", await response.Code());
    }

    [Fact]
    public async Task Rerouting_away_and_back_supersedes_the_original_recommendation()
    {
        var request = await CreateRequestAsync("IT");
        var recommendationId = await AddRecommendationAsync(request.Id, "FAC");

        Assert.Equal(HttpStatusCode.OK, (await RerouteAsync(request.Id, "FAC")).StatusCode);
        Assert.Equal(HttpStatusCode.OK, (await RerouteAsync(request.Id, "IT")).StatusCode);
        var detail = await (await api.As("u-ben").GetAsync($"/api/requests/{request.Id}")).Read<RequestDetailDto>();
        Assert.Equal("IT", detail.DepartmentId);
        var recommendations = await (await api.As("u-ben").GetAsync($"/api/requests/{request.Id}/triage-recommendations")).Read<List<RecommendationDto>>();
        var superseded = Assert.Single(recommendations, r => r.Id == recommendationId);
        Assert.Equal("Superseded", superseded.Status);
        Assert.Equal("IT", superseded.DepartmentAtRecommendation);

        var response = await ConfirmAsync("u-ben", request.Id, recommendationId);

        Assert.Equal(HttpStatusCode.Conflict, response.StatusCode);
        Assert.Equal("recommendation.stale", await response.Code());
    }

    [Fact]
    public async Task Concurrent_recommendation_superseding_confirmation_is_rejected_as_stale_by_postgres_xmin()
    {
        var request = await CreateRequestAsync("IT");
        var recommendationId = await AddRecommendationAsync(request.Id, "IT");
        await using var confirmingScope = api.Factory.Services.CreateAsyncScope();
        await using var generatingScope = api.Factory.Services.CreateAsyncScope();
        var confirmingDb = confirmingScope.ServiceProvider.GetRequiredService<RequestHubDbContext>();
        var generatingDb = generatingScope.ServiceProvider.GetRequiredService<RequestHubDbContext>();
        var confirmingRecommendation = await confirmingDb.Recommendations.SingleAsync(r => r.Id == recommendationId);
        var originalVersion = confirmingRecommendation.Version;

        var superseded = await generatingDb.Recommendations.SingleAsync(r => r.Id == recommendationId);
        superseded.Status = RecommendationStatus.Superseded;
        generatingDb.Recommendations.Add(new TriageRecommendation
        {
            Id = Guid.NewGuid(),
            RequestId = superseded.RequestId,
            Provider = "sample-rules",
            IsSample = true,
            SuggestedDepartmentId = "IT",
            SuggestedPriority = RequestPriority.Normal,
            Rationale = "A newer recommendation supersedes the earlier one.",
            PolicyRefs = ["POL-ROUTE-001@1.2"],
            Confidence = 0.8,
            DepartmentAtRecommendation = "IT",
            CreatedById = "u-ben",
            CreatedAt = DateTimeOffset.UtcNow.AddSeconds(1),
        });
        await generatingDb.SaveChangesAsync();
        Assert.NotEqual(originalVersion, superseded.Version);

        confirmingRecommendation.Status = RecommendationStatus.Confirmed;
        await Assert.ThrowsAsync<DbUpdateConcurrencyException>(() => confirmingDb.SaveChangesAsync());

        confirmingDb.ChangeTracker.Clear();
        Assert.Equal(RecommendationStatus.Superseded,
            (await confirmingDb.Recommendations.SingleAsync(r => r.Id == recommendationId)).Status);
        var response = await ConfirmAsync("u-ben", request.Id, recommendationId);
        Assert.Equal(HttpStatusCode.Conflict, response.StatusCode);
        Assert.Equal("recommendation.stale", await response.Code());
    }

    [Fact]
    public async Task Duplicate_confirmation_returns_already_confirmed_without_a_second_audit()
    {
        var request = await CreateRequestAsync("IT");
        var recommendationId = await AddRecommendationAsync(request.Id, "FAC");

        Assert.Equal(HttpStatusCode.OK, (await ConfirmAsync("u-ben", request.Id, recommendationId)).StatusCode);
        var duplicate = await ConfirmAsync("u-ben", request.Id, recommendationId);

        Assert.Equal(HttpStatusCode.Conflict, duplicate.StatusCode);
        Assert.Equal("recommendation.already_confirmed", await duplicate.Code());
        var history = await (await api.As("u-ava").GetAsync($"/api/requests/{request.Id}/history")).Read<List<AuditEventDto>>();
        Assert.Single(history, e => e.Action == "triage.confirmed");
    }

    [Fact]
    public async Task Concurrent_confirmation_records_exactly_one_audit()
    {
        var request = await CreateRequestAsync("IT");
        var recommendationId = await AddRecommendationAsync(request.Id, "FAC");

        var responses = await Task.WhenAll(
            ConfirmAsync("u-ben", request.Id, recommendationId),
            ConfirmAsync("u-dan", request.Id, recommendationId));

        Assert.Single(responses, r => r.StatusCode == HttpStatusCode.OK);
        Assert.Single(responses, r => r.StatusCode == HttpStatusCode.Conflict);
        var conflict = responses.Single(r => r.StatusCode == HttpStatusCode.Conflict);
        Assert.Equal("recommendation.already_confirmed", await conflict.Code());
        var history = await (await api.As("u-ava").GetAsync($"/api/requests/{request.Id}/history")).Read<List<AuditEventDto>>();
        Assert.Single(history, e => e.Action == "triage.confirmed");
    }

    [Theory]
    [InlineData("Approved")]
    [InlineData("Rejected")]
    public async Task Approved_or_rejected_request_cannot_have_its_recommendation_confirmed(string outcome)
    {
        var request = await CreateRequestAsync("IT");
        var recommendationId = await AddRecommendationAsync(request.Id, "FAC");
        var decision = await api.As("u-chloe").PostJson($"/api/requests/{request.Id}/decisions",
            new { outcome, comment = outcome == "Rejected" ? "Outside the request scope." : null });
        Assert.Equal(HttpStatusCode.Created, decision.StatusCode);

        var response = await ConfirmAsync("u-dan", request.Id, recommendationId);

        Assert.Equal(HttpStatusCode.Conflict, response.StatusCode);
        Assert.Equal("request.terminal", await response.Code());
    }

    [Fact]
    public async Task Admin_can_confirm_a_recommendation()
    {
        var request = await CreateRequestAsync("IT");
        var recommendationId = await AddRecommendationAsync(request.Id, "FAC");

        var response = await ConfirmAsync("u-dan", request.Id, recommendationId);

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.Equal("FAC", (await response.Read<RequestDetailDto>()).DepartmentId);
    }

    private async Task<RequestDetailDto> CreateRequestAsync(string department) =>
        await (await api.As("u-ava").PostJson("/api/requests", new
        {
            title = $"Routing check {Guid.NewGuid():N}",
            description = "A synthetic request for routing confirmation tests.",
            category = "equipment",
            departmentId = department,
            priority = "Normal",
        })).Read<RequestDetailDto>();

    private async Task<Guid> AddRecommendationAsync(string publicId, string suggestedDepartment, RecommendationStatus status = RecommendationStatus.Proposed)
    {
        await using var scope = api.Factory.Services.CreateAsyncScope();
        var db = scope.ServiceProvider.GetRequiredService<RequestHubDbContext>();
        var request = await db.Requests.Include(r => r.Recommendations).SingleAsync(r => r.Number == RequestNumber(publicId));
        var recommendation = request.Recommendations.FirstOrDefault();
        if (recommendation is null)
        {
            recommendation = new TriageRecommendation
            {
                Id = Guid.NewGuid(),
                RequestId = request.Id,
                Provider = "sample-rules",
                IsSample = true,
                SuggestedDepartmentId = suggestedDepartment,
                SuggestedPriority = RequestPriority.Urgent,
                Rationale = "Synthetic routing recommendation for the integration test.",
                PolicyRefs = ["POL-ROUTE-003@2.1"],
                Confidence = 0.9,
                DepartmentAtRecommendation = request.DepartmentId,
                CreatedById = "u-ben",
                CreatedAt = DateTimeOffset.UtcNow,
            };
            db.Recommendations.Add(recommendation);
        }

        recommendation.SuggestedDepartmentId = suggestedDepartment;
        recommendation.Status = status;
        recommendation.DepartmentAtRecommendation = request.DepartmentId;
        await db.SaveChangesAsync();
        return recommendation.Id;
    }

    private async Task SetRequestDepartmentAsync(string publicId, string department)
    {
        await using var scope = api.Factory.Services.CreateAsyncScope();
        var db = scope.ServiceProvider.GetRequiredService<RequestHubDbContext>();
        var request = await db.Requests.SingleAsync(r => r.Number == RequestNumber(publicId));
        request.DepartmentId = department;
        await db.SaveChangesAsync();
    }

    private Task<HttpResponseMessage> ConfirmAsync(string persona, string publicId, Guid recommendationId) =>
        api.As(persona).PostAsync($"/api/requests/{publicId}/triage-recommendations/{recommendationId}/confirm", null);

    private Task<HttpResponseMessage> RerouteAsync(string publicId, string departmentId) =>
        api.As("u-ben").PutAsJsonAsync($"/api/requests/{publicId}/routing", new { departmentId, reason = "Routing regression test." });

    private static int RequestNumber(string publicId) => int.Parse(publicId.AsSpan("REQ-".Length));
}

public sealed class ConcurrentRecommendationFixture : ApiFixture
{
    protected override void ConfigureTestServices(IServiceCollection services)
    {
        services.RemoveAll<ITriageProvider>();
        services.AddSingleton<ITriageProvider, ConcurrentRecommendationProvider>();
    }
}

public sealed class ConcurrentRecommendationProvider : ITriageProvider
{
    private static int calls;
    private static TaskCompletionSource bothCalls = NewSignal();

    public string Id => "test-concurrent-recommendation";
    public bool IsSample => true;

    public static void Reset()
    {
        Interlocked.Exchange(ref calls, 0);
        bothCalls = NewSignal();
    }

    public async Task<TriageResult> RecommendAsync(TriageContext context, CancellationToken cancellationToken)
    {
        if (Interlocked.Increment(ref calls) == 2)
        {
            bothCalls.TrySetResult();
        }

        await bothCalls.Task.WaitAsync(cancellationToken);
        return new TriageResult("IT", "Normal", "Concurrent recommendation test.", ["POL-ROUTE-001"], 0.8, false);
    }

    private static TaskCompletionSource NewSignal() => new(TaskCreationOptions.RunContinuationsAsynchronously);
}

public sealed class ConcurrentRecommendationTests(ConcurrentRecommendationFixture api) : IClassFixture<ConcurrentRecommendationFixture>
{
    [Fact]
    public async Task Concurrent_generation_conflict_returns_a_stable_conflict_instead_of_server_error()
    {
        ConcurrentRecommendationProvider.Reset();
        var request = await (await api.As("u-ava").PostJson("/api/requests", new
        {
            title = $"Concurrent triage {Guid.NewGuid():N}",
            description = "A synthetic request for concurrent recommendation testing.",
            category = "equipment",
            departmentId = "IT",
            priority = "Normal",
        })).Read<RequestDetailDto>();

        await using (var scope = api.Factory.Services.CreateAsyncScope())
        {
            var db = scope.ServiceProvider.GetRequiredService<RequestHubDbContext>();
            var requestNumber = int.Parse(request.Id.AsSpan("REQ-".Length));
            var entity = await db.Requests.SingleAsync(r => r.Number == requestNumber);
            db.Recommendations.Add(new TriageRecommendation
            {
                Id = Guid.NewGuid(),
                RequestId = entity.Id,
                Provider = "sample-rules",
                IsSample = true,
                SuggestedDepartmentId = "IT",
                SuggestedPriority = RequestPriority.Normal,
                Rationale = "Existing recommendation for the concurrency test.",
                PolicyRefs = ["POL-ROUTE-001@1.2"],
                Confidence = 0.8,
                DepartmentAtRecommendation = "IT",
                CreatedById = "u-ben",
                CreatedAt = DateTimeOffset.UtcNow,
            });
            await db.SaveChangesAsync();
        }

        var responses = await Task.WhenAll(
            api.As("u-ben").PostAsync($"/api/requests/{request.Id}/triage-recommendations", null),
            api.As("u-ben").PostAsync($"/api/requests/{request.Id}/triage-recommendations", null));

        Assert.Single(responses, response => response.StatusCode == HttpStatusCode.Created);
        var conflict = Assert.Single(responses, response => response.StatusCode == HttpStatusCode.Conflict);
        Assert.Equal("recommendation.concurrent_update", await conflict.Code());
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
