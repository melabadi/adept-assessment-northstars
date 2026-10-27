using System.Net;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.DependencyInjection.Extensions;
using RequestHub.Core.Data;
using RequestHub.Core.Domain;
using RequestHub.Core.Services;
using RequestHub.Core.Triage;

namespace RequestHub.Tests;

public sealed class RecommendationConfirmationTests(ApiFixture api) : IClassFixture<ApiFixture>
{
    [Fact]
    public async Task Reviewer_confirmation_routes_audits_and_preserves_nonrouting_fields()
    {
        var requestId = await CreateRequestAsync(api);
        var (recommendationId, _) = await AddRecommendationAsync(api, requestId, "FAC");
        var response = await api.As("u-ben").PostAsync(ConfirmPath(requestId, recommendationId), null, TestContext.Current.CancellationToken);

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var detail = await response.Read<RequestDetailDto>();
        Assert.Equal("FAC", detail.DepartmentId);
        Assert.Equal("InReview", detail.Status);
        Assert.Equal("Normal", detail.Priority);
        Assert.Null(detail.Decision);
        Assert.Equal("Confirmed", detail.LatestRecommendation!.Status);
        Assert.Equal("Ben Okafor", detail.LatestRecommendation.ConfirmedBy!.DisplayName);

        var history = await (await api.As("u-ava").GetAsync($"/api/requests/{requestId}/history", TestContext.Current.CancellationToken)).Read<List<AuditEventDto>>();
        var audit = Assert.Single(history, e => e.Action == "triage.confirmed");
        Assert.Equal("u-ben", audit.Actor.Id);
        Assert.Equal(recommendationId, audit.Details.GetProperty("recommendationId").GetGuid());
        Assert.Equal("IT", audit.Details.GetProperty("fromDepartment").GetString());
        Assert.Equal("FAC", audit.Details.GetProperty("toDepartment").GetString());
        Assert.Equal("sample-rules", audit.Details.GetProperty("provider").GetString());
        Assert.Contains("POL-ROUTE-001@1.2", audit.Details.GetProperty("policyRefs").EnumerateArray().Select(x => x.GetString()));

        await using var scope = api.Factory.Services.CreateAsyncScope();
        var db = scope.ServiceProvider.GetRequiredService<RequestHubDbContext>();
        var requestDbId = await RequestDbIdAsync(db, requestId);
        var recipients = await db.Notifications.Where(n => n.RequestId == requestDbId && n.Type == "request.routed")
            .Select(n => n.Recipient).Order().ToListAsync(TestContext.Current.CancellationToken);
        Assert.Equal(["u-ben", "u-dan"], recipients);
    }

    public sealed class RecommendationRaceFixture : ApiFixture
    {
        public PausedTriageProvider Provider { get; } = new();

        protected override void ConfigureTestServices(IServiceCollection services)
        {
            services.RemoveAll<ITriageProvider>();
            services.AddSingleton<ITriageProvider>(Provider);
        }
    }

    public sealed class PausedTriageProvider : ITriageProvider
    {
        private readonly TaskCompletionSource started = new(TaskCreationOptions.RunContinuationsAsynchronously);
        private readonly TaskCompletionSource release = new(TaskCreationOptions.RunContinuationsAsynchronously);
        private int calls;

        public string Id => "test-paused";
        public bool IsSample => false;
        public Task BothCallsStarted => started.Task;
        public void Release() => release.TrySetResult();

        public async Task<TriageResult> RecommendAsync(TriageContext context, CancellationToken cancellationToken)
        {
            if (Interlocked.Increment(ref calls) == 2)
            {
                started.TrySetResult();
            }

            await release.Task.WaitAsync(cancellationToken);
            return new TriageResult("IT", "Normal", "Test recommendation.", ["POL-ROUTE-001"], 0.8, false);
        }
    }

    public sealed class ConcurrentRecommendationTests(RecommendationRaceFixture api) : IClassFixture<RecommendationRaceFixture>
    {
        [Fact]
        public async Task Concurrent_recommendations_leave_only_one_proposed_record()
        {
            var create = await api.As("u-ava").PostJson("/api/requests", new
            {
                title = $"Concurrent recommendation {Guid.NewGuid():N}"[..30],
                description = "A request for serialized recommendation tests.",
                category = "equipment",
                departmentId = "IT",
                priority = "Normal",
            });
            Assert.Equal(HttpStatusCode.Created, create.StatusCode);
            var requestId = (await create.Read<RequestDetailDto>()).Id;
            var path = $"/api/requests/{requestId}/triage-recommendations";
            var reviewer = api.As("u-ben");
            var first = reviewer.PostAsync(path, null, TestContext.Current.CancellationToken);
            var second = reviewer.PostAsync(path, null, TestContext.Current.CancellationToken);
            await api.Provider.BothCallsStarted.WaitAsync(TestContext.Current.CancellationToken);
            api.Provider.Release();
            var responses = await Task.WhenAll(first, second);

            Assert.Single(responses, response => response.StatusCode == HttpStatusCode.Created);
            var conflict = Assert.Single(responses, response => response.StatusCode == HttpStatusCode.Conflict);
            Assert.Equal("triage.concurrent_recommendation", await conflict.Code());
            var recommendations = await (await reviewer.GetAsync(
                path,
                TestContext.Current.CancellationToken)).Read<List<RecommendationDto>>();
            Assert.Single(recommendations, recommendation => recommendation.Status == "Proposed");
        }
    }

    [Fact]
    public async Task Same_department_confirmation_marks_recommendation_without_routing()
    {
        var requestId = await CreateRequestAsync(api);
        var (recommendationId, _) = await AddRecommendationAsync(api, requestId, "IT");
        var response = await api.As("u-dan").PostAsync(ConfirmPath(requestId, recommendationId), null, TestContext.Current.CancellationToken);

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var detail = await response.Read<RequestDetailDto>();
        Assert.Equal("IT", detail.DepartmentId);
        Assert.Equal("Submitted", detail.Status);
        Assert.Equal("Confirmed", detail.LatestRecommendation!.Status);
        Assert.Equal("Dan Rivera", detail.LatestRecommendation.ConfirmedBy!.DisplayName);

        var history = await (await api.As("u-ava").GetAsync($"/api/requests/{requestId}/history", TestContext.Current.CancellationToken)).Read<List<AuditEventDto>>();
        Assert.Single(history, e => e.Action == "triage.confirmed");
        await using var scope = api.Factory.Services.CreateAsyncScope();
        var db = scope.ServiceProvider.GetRequiredService<RequestHubDbContext>();
        var requestDbId = await RequestDbIdAsync(db, requestId);
        Assert.Empty(await db.Notifications.Where(n => n.RequestId == requestDbId && n.Type == "request.routed")
            .ToListAsync(TestContext.Current.CancellationToken));
    }

    [Theory]
    [InlineData("u-ava", "IT", "FAC")]
    [InlineData("u-chloe", "IT", "FAC")]
    [InlineData("u-grace", "IT", "FIN")]
    public async Task Requester_approver_or_reviewer_without_current_department_access_is_forbidden(string user, string currentDepartment, string suggestedDepartment)
    {
        var requestId = await CreateRequestAsync(api, currentDepartment);
        var (recommendationId, _) = await AddRecommendationAsync(api, requestId, suggestedDepartment);
        var response = await api.As(user).PostAsync(ConfirmPath(requestId, recommendationId), null, TestContext.Current.CancellationToken);

        Assert.Equal(HttpStatusCode.Forbidden, response.StatusCode);
    }

    [Fact]
    public async Task Reviewer_without_suggested_department_access_is_forbidden()
    {
        var requestId = await CreateRequestAsync(api, "FIN");
        var (recommendationId, _) = await AddRecommendationAsync(api, requestId, "IT");
        var response = await api.As("u-grace").PostAsync(ConfirmPath(requestId, recommendationId), null, TestContext.Current.CancellationToken);

        Assert.Equal(HttpStatusCode.Forbidden, response.StatusCode);
    }

    [Theory]
    [InlineData("department")]
    [InlineData("superseded")]
    public async Task Stale_recommendations_are_conflicts(string staleReason)
    {
        var (recommendationId, requestId) = await AddRecommendationAsync(
            api,
            await CreateRequestAsync(api),
            "FAC",
            staleReason == "superseded" ? RecommendationStatus.Superseded : RecommendationStatus.Proposed,
            staleReason == "department" ? "FAC" : null);
        var response = await api.As("u-ben").PostAsync(ConfirmPath(requestId, recommendationId), null, TestContext.Current.CancellationToken);

        Assert.Equal(HttpStatusCode.Conflict, response.StatusCode);
        Assert.Equal("recommendation.stale", await response.Code());
    }

    [Fact]
    public async Task Duplicate_confirmation_returns_conflict_without_a_second_audit()
    {
        var requestId = await CreateRequestAsync(api);
        var (recommendationId, _) = await AddRecommendationAsync(api, requestId, "FAC");
        var reviewer = api.As("u-ben");
        Assert.Equal(HttpStatusCode.OK, (await reviewer.PostAsync(ConfirmPath(requestId, recommendationId), null, TestContext.Current.CancellationToken)).StatusCode);

        var duplicate = await reviewer.PostAsync(ConfirmPath(requestId, recommendationId), null, TestContext.Current.CancellationToken);

        Assert.Equal(HttpStatusCode.Conflict, duplicate.StatusCode);
        Assert.Equal("recommendation.already_confirmed", await duplicate.Code());
        var history = await (await api.As("u-ava").GetAsync($"/api/requests/{requestId}/history", TestContext.Current.CancellationToken)).Read<List<AuditEventDto>>();
        Assert.Single(history, e => e.Action == "triage.confirmed");
    }

    [Fact]
    public async Task Concurrent_confirmations_claim_a_recommendation_once()
    {
        var requestId = await CreateRequestAsync(api);
        var (recommendationId, _) = await AddRecommendationAsync(api, requestId, "FAC");
        var reviewer = api.As("u-ben");
        var attempts = await Task.WhenAll(Enumerable.Range(0, 6).Select(_ =>
            reviewer.PostAsync(ConfirmPath(requestId, recommendationId), null, TestContext.Current.CancellationToken)));

        Assert.Single(attempts, response => response.StatusCode == HttpStatusCode.OK);
        var conflicts = attempts.Where(response => response.StatusCode != HttpStatusCode.OK).ToList();
        Assert.Equal(5, conflicts.Count);
        foreach (var conflict in conflicts)
        {
            Assert.Equal(HttpStatusCode.Conflict, conflict.StatusCode);
            Assert.Equal("recommendation.already_confirmed", await conflict.Code());
        }

        var history = await (await api.As("u-ava").GetAsync(
            $"/api/requests/{requestId}/history",
            TestContext.Current.CancellationToken)).Read<List<AuditEventDto>>();
        Assert.Single(history, e => e.Action == "triage.confirmed");
    }

    [Fact]
    public async Task Terminal_request_cannot_confirm_routing()
    {
        var (recommendationId, requestId) = await AddRecommendationAsync(api, "REQ-1004", "FAC");
        var response = await api.As("u-dan").PostAsync(ConfirmPath(requestId, recommendationId), null, TestContext.Current.CancellationToken);

        Assert.Equal(HttpStatusCode.Conflict, response.StatusCode);
        Assert.Equal("request.terminal", await response.Code());
    }

    private static string ConfirmPath(string requestId, Guid recommendationId) =>
        $"/api/requests/{requestId}/triage-recommendations/{recommendationId}/confirm";

    private static async Task<string> CreateRequestAsync(ApiFixture api, string department = "IT")
    {
        var response = await api.As("u-ava").PostJson("/api/requests", new
        {
            title = $"Confirmation test request {Guid.NewGuid():N}"[..30],
            description = "A request created for recommendation confirmation tests.",
            category = department == "FIN" ? "purchase" : "equipment",
            departmentId = department,
            priority = "Normal",
        });
        Assert.Equal(HttpStatusCode.Created, response.StatusCode);
        return (await response.Read<RequestDetailDto>()).Id;
    }

    private static async Task<(Guid RecommendationId, string RequestId)> AddRecommendationAsync(
        ApiFixture api,
        string requestId,
        string suggestedDepartment,
        RecommendationStatus status = RecommendationStatus.Proposed,
        string? departmentAtRecommendation = null)
    {
        await using var scope = api.Factory.Services.CreateAsyncScope();
        var db = scope.ServiceProvider.GetRequiredService<RequestHubDbContext>();
        Assert.True(Request.TryParsePublicId(requestId, out var number));
        var request = await db.Requests.SingleAsync(r => r.Number == number);

        var recommendation = new TriageRecommendation
        {
            Id = Guid.NewGuid(),
            RequestId = request.Id,
            Provider = "sample-rules",
            IsSample = true,
            SuggestedDepartmentId = suggestedDepartment,
            SuggestedPriority = request.Priority,
            Rationale = "Test recommendation.",
            PolicyRefs = ["POL-ROUTE-001@1.2"],
            Confidence = 0.8,
            Status = status,
            DepartmentAtRecommendation = departmentAtRecommendation ?? request.DepartmentId,
            CreatedById = "u-ben",
            CreatedAt = DateTimeOffset.UtcNow,
        };
        db.Recommendations.Add(recommendation);
        await db.SaveChangesAsync();
        return (recommendation.Id, requestId);
    }

    private static async Task<Guid> RequestDbIdAsync(RequestHubDbContext db, string requestId)
    {
        Assert.True(Request.TryParsePublicId(requestId, out var number));
        return await db.Requests.Where(r => r.Number == number).Select(r => r.Id).SingleAsync();
    }
}
