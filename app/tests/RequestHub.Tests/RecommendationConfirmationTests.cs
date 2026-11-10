using System.Net;
using System.Net.Http.Json;
using System.Text.Json;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using RequestHub.Core.Data;
using RequestHub.Core.Domain;
using RequestHub.Core.Services;

namespace RequestHub.Tests;

public sealed class RecommendationConfirmationTests(ApiFixture api) : IClassFixture<ApiFixture>
{
    [Fact]
    public async Task Reviewer_confirms_route_with_manual_reroute_status_notifications_and_audit()
    {
        var client = api.As("u-ben");
        var before = await (await client.GetAsync("/api/requests/REQ-1001")).Read<RequestDetailDto>();
        var recommendation = await Recommend("REQ-1001");
        await SetSuggestedDepartment(recommendation.Id, "FAC");
        recommendation = recommendation with { SuggestedDepartmentId = "FAC" };

        var response = await client.PostAsync(ConfirmPath("REQ-1001", recommendation.Id), null);

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var after = await response.Read<RequestDetailDto>();
        Assert.Equal(recommendation.SuggestedDepartmentId, after.DepartmentId);
        Assert.Equal("InReview", after.Status);
        Assert.Equal(before.Priority, after.Priority);
        Assert.Equal(before.Decision, after.Decision);
        Assert.Equal("Confirmed", after.LatestRecommendation!.Status);
        Assert.Equal("Ben Okafor", after.LatestRecommendation.ConfirmedBy!.DisplayName);

        await using var scope = api.Factory.Services.CreateAsyncScope();
        var db = scope.ServiceProvider.GetRequiredService<RequestHubDbContext>();
        var events = await db.AuditEvents.Where(e => e.RequestId != null && e.Action == "triage.confirmed").ToListAsync();
        var audit = Assert.Single(events.Where(e => ConfirmationMatches(e.Details, recommendation.Id)));
        using var details = JsonDocument.Parse(audit.Details);
        var data = details.RootElement;
        Assert.Equal(recommendation.Id, data.GetProperty("recommendationId").GetGuid());
        Assert.Equal(before.DepartmentId, data.GetProperty("from").GetString());
        Assert.Equal(recommendation.SuggestedDepartmentId, data.GetProperty("to").GetString());
        Assert.Equal(recommendation.Provider, data.GetProperty("provider").GetString());
        var policyRefs = data.GetProperty("policyRefs").EnumerateArray().Select(p => p.GetString()).ToArray();
        Assert.Equal(recommendation.PolicyRefs.Select(p => $"{p.PolicyId}@{p.Version}"), policyRefs);
        Assert.True(await db.Notifications.AnyAsync(n => n.RequestId == audit.RequestId && n.Type == "request.routed"));
    }

    [Fact]
    public async Task Reviewer_confirms_same_department_without_reroute_status_or_notifications()
    {
        const string requestId = "REQ-1009";
        var recommendation = await Recommend(requestId);
        var current = await (await api.As("u-dan").GetAsync($"/api/requests/{requestId}")).Read<RequestDetailDto>();
        await SetSuggestedDepartment(recommendation.Id, current.DepartmentId);
        var notificationCount = await CountNotifications(requestId);

        var response = await api.As("u-dan").PostAsync(ConfirmPath(requestId, recommendation.Id), null);

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var after = await response.Read<RequestDetailDto>();
        Assert.Equal(current.DepartmentId, after.DepartmentId);
        Assert.Equal(current.Status, after.Status);
        Assert.Equal(current.Priority, after.Priority);
        Assert.Null(after.Decision);
        Assert.Equal("Confirmed", after.LatestRecommendation!.Status);
        Assert.Equal(notificationCount, await CountNotifications(requestId));
        Assert.Equal(1, await CountConfirmAudits(recommendation.Id));
    }

    [Fact]
    public async Task Requester_and_non_reviewer_cannot_confirm_a_recommendation()
    {
        var created = await api.As("u-ben").PostJson("/api/requests", new
        {
            title = "Reviewer-owned laptop request",
            description = "This request belongs to a reviewer and must not be self-confirmed.",
            category = "equipment",
            departmentId = "IT",
            priority = "Normal",
        });
        Assert.Equal(HttpStatusCode.Created, created.StatusCode);
        var request = await created.Read<RequestDetailDto>();
        var requestId = request.Id;
        var recommendation = await Recommend(requestId);

        var requesterResponse = await api.As("u-ava").PostAsync(ConfirmPath(requestId, recommendation.Id), null);
        var selfResponse = await api.As(request.Requester.Id).PostAsync(ConfirmPath(requestId, recommendation.Id), null);
        var approverResponse = await api.As("u-chloe").PostAsync(ConfirmPath(requestId, recommendation.Id), null);

        Assert.Equal(HttpStatusCode.Forbidden, requesterResponse.StatusCode);
        Assert.Equal(HttpStatusCode.Forbidden, selfResponse.StatusCode);
        Assert.Equal(HttpStatusCode.Forbidden, approverResponse.StatusCode);
    }

    [Fact]
    public async Task Reviewer_without_access_to_suggested_department_cannot_confirm()
    {
        const string requestId = "REQ-1001";
        var recommendation = await Recommend(requestId);
        await SetSuggestedDepartment(recommendation.Id, "FIN");

        var response = await api.As("u-ben").PostAsync(ConfirmPath(requestId, recommendation.Id), null);

        Assert.Equal(HttpStatusCode.Forbidden, response.StatusCode);
    }

    [Fact]
    public async Task Reviewer_without_access_to_current_department_cannot_confirm()
    {
        const string requestId = "REQ-1001";
        var recommendation = await Recommend(requestId);

        var response = await api.As("u-grace").PostAsync(ConfirmPath(requestId, recommendation.Id), null);

        Assert.Equal(HttpStatusCode.Forbidden, response.StatusCode);
    }

    [Fact]
    public async Task Superseded_recommendation_cannot_be_confirmed()
    {
        const string requestId = "REQ-1012";
        var stale = await Recommend(requestId);
        await Recommend(requestId);

        var response = await api.As("u-dan").PostAsync(ConfirmPath(requestId, stale.Id), null);

        Assert.Equal(HttpStatusCode.Conflict, response.StatusCode);
        Assert.Equal("recommendation.stale", await response.Code());
    }

    [Fact]
    public async Task Recommendation_for_changed_department_cannot_be_confirmed()
    {
        const string requestId = "REQ-1014";
        var recommendation = await Recommend(requestId);
        var current = await (await api.As("u-dan").GetAsync($"/api/requests/{requestId}")).Read<RequestDetailDto>();
        var destination = current.DepartmentId == "FIN" ? "IT" : "FIN";
        var reroute = await api.As("u-dan").PutAsJsonAsync($"/api/requests/{requestId}/routing", new { departmentId = destination, reason = "Changed route" });
        Assert.Equal(HttpStatusCode.OK, reroute.StatusCode);

        var response = await api.As("u-dan").PostAsync(ConfirmPath(requestId, recommendation.Id), null);

        Assert.Equal(HttpStatusCode.Conflict, response.StatusCode);
        Assert.Equal("recommendation.stale", await response.Code());
    }

    [Fact]
    public async Task Repeated_confirmation_returns_already_confirmed_without_a_second_audit()
    {
        const string requestId = "REQ-1010";
        var recommendation = await Recommend(requestId);
        var current = await (await api.As("u-dan").GetAsync($"/api/requests/{requestId}")).Read<RequestDetailDto>();
        await SetSuggestedDepartment(recommendation.Id, current.DepartmentId);
        Assert.Equal(HttpStatusCode.OK, (await api.As("u-dan").PostAsync(ConfirmPath(requestId, recommendation.Id), null)).StatusCode);

        var repeated = await api.As("u-dan").PostAsync(ConfirmPath(requestId, recommendation.Id), null);

        Assert.Equal(HttpStatusCode.Conflict, repeated.StatusCode);
        Assert.Equal("recommendation.already_confirmed", await repeated.Code());
        Assert.Equal(1, await CountConfirmAudits(recommendation.Id));
    }

    [Fact]
    public async Task Terminal_request_cannot_confirm_recommendation()
    {
        const string requestId = "REQ-1004";
        var recommendationId = await AddRecommendationToRequest(requestId);

        var response = await api.As("u-dan").PostAsync(ConfirmPath(requestId, recommendationId), null);

        Assert.Equal(HttpStatusCode.Conflict, response.StatusCode);
        Assert.Equal("request.terminal", await response.Code());
    }

    private async Task<RecommendationDto> Recommend(string requestId)
    {
        var response = await api.As("u-dan").PostAsync($"/api/requests/{requestId}/triage-recommendations", null);
        Assert.Equal(HttpStatusCode.Created, response.StatusCode);
        return await response.Read<RecommendationDto>();
    }

    private async Task SetSuggestedDepartment(Guid recommendationId, string departmentId)
    {
        await using var scope = api.Factory.Services.CreateAsyncScope();
        var db = scope.ServiceProvider.GetRequiredService<RequestHubDbContext>();
        var recommendation = await db.Recommendations.SingleAsync(r => r.Id == recommendationId);
        recommendation.SuggestedDepartmentId = departmentId;
        await db.SaveChangesAsync();
    }

    private async Task<Guid> AddRecommendationToRequest(string requestId)
    {
        await using var scope = api.Factory.Services.CreateAsyncScope();
        var db = scope.ServiceProvider.GetRequiredService<RequestHubDbContext>();
        var number = int.Parse(requestId.Substring("REQ-".Length));
        var request = await db.Requests.SingleAsync(r => r.Number == number);
        var recommendation = new TriageRecommendation
        {
            Id = Guid.NewGuid(),
            RequestId = request.Id,
            Provider = "sample-rules",
            IsSample = true,
            SuggestedDepartmentId = request.DepartmentId,
            SuggestedPriority = request.Priority,
            Rationale = "Test recommendation.",
            DepartmentAtRecommendation = request.DepartmentId,
            CreatedById = "u-dan",
            CreatedAt = request.UpdatedAt,
        };
        db.Recommendations.Add(recommendation);
        await db.SaveChangesAsync();
        return recommendation.Id;
    }

    private async Task<int> CountNotifications(string requestId)
    {
        await using var scope = api.Factory.Services.CreateAsyncScope();
        var db = scope.ServiceProvider.GetRequiredService<RequestHubDbContext>();
        var number = int.Parse(requestId.Substring("REQ-".Length));
        var requestDbId = await db.Requests.Where(r => r.Number == number).Select(r => r.Id).SingleAsync();
        return await db.Notifications.CountAsync(n => n.RequestId == requestDbId);
    }

    private async Task<int> CountConfirmAudits(Guid recommendationId)
    {
        await using var scope = api.Factory.Services.CreateAsyncScope();
        var db = scope.ServiceProvider.GetRequiredService<RequestHubDbContext>();
        var events = await db.AuditEvents.Where(e => e.Action == "triage.confirmed").Select(e => e.Details).ToListAsync();
        return events.Count(details => ConfirmationMatches(details, recommendationId));
    }

    private static string ConfirmPath(string requestId, Guid recommendationId) =>
        $"/api/requests/{requestId}/triage-recommendations/{recommendationId}/confirm";

    private static bool ConfirmationMatches(string details, Guid recommendationId)
    {
        using var document = JsonDocument.Parse(details);
        return document.RootElement.TryGetProperty("recommendationId", out var value)
            && value.TryGetGuid(out var id)
            && id == recommendationId;
    }
}
