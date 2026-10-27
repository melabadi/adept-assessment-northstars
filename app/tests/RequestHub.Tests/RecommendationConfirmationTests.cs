using System.Net;
using System.Net.Http.Json;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using RequestHub.Core.Data;
using RequestHub.Core.Domain;
using RequestHub.Core.Services;

namespace RequestHub.Tests;

public sealed class RecommendationConfirmationTests(ApiFixture api) : IClassFixture<ApiFixture>
{
    private static object NewRequest(string department = "IT", string title = "Replacement chair for the north wing", string priority = "High", string category = "facilities") => new
    {
        title,
        description = "A replacement chair is needed for the shared workspace.",
        category,
        departmentId = department,
        priority,
    };

    private async Task<(string RequestId, RecommendationDto Recommendation)> CreateRequestAndRecommendation(
        string department = "IT", string title = "Replacement chair for the north wing", string category = "facilities", string triagePersona = "u-ben")
    {
        var created = await api.As("u-ava").PostJson("/api/requests", NewRequest(department, title, category: category));
        Assert.Equal(HttpStatusCode.Created, created.StatusCode);
        var request = await created.Read<RequestDetailDto>();
        var response = await api.As(triagePersona).PostAsync($"/api/requests/{request.Id}/triage-recommendations", null);
        Assert.Equal(HttpStatusCode.Created, response.StatusCode);
        var recommendation = await response.Read<RecommendationDto>();
        return (request.Id, recommendation);
    }

    [Fact]
    public async Task Reviewer_confirms_different_department_with_reroute_notifications_and_one_audit()
    {
        var (id, recommendation) = await CreateRequestAndRecommendation();
        Assert.Equal("IT", recommendation.DepartmentAtRecommendation);
        Assert.Equal("FAC", recommendation.SuggestedDepartmentId);
        var reviewerView = await (await api.As("u-ben").GetAsync($"/api/requests/{id}")).Read<RequestDetailDto>();
        var requesterView = await (await api.As("u-ava").GetAsync($"/api/requests/{id}")).Read<RequestDetailDto>();
        Assert.True(reviewerView.Permissions.CanConfirmRecommendation);
        Assert.False(requesterView.Permissions.CanConfirmRecommendation);

        var response = await api.As("u-ben").PostAsync(
            $"/api/requests/{id}/triage-recommendations/{recommendation.Id}/confirm", null);
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var detail = await response.Read<RequestDetailDto>();
        Assert.Equal("FAC", detail.DepartmentId);
        Assert.Equal("InReview", detail.Status);
        Assert.Equal("High", detail.Priority);
        Assert.Null(detail.Decision);
        Assert.Equal("Confirmed", detail.LatestRecommendation!.Status);
        Assert.Equal("u-ben", detail.LatestRecommendation.ConfirmedBy!.Id);

        var history = await (await api.As("u-ava").GetAsync($"/api/requests/{id}/history")).Read<List<AuditEventDto>>();
        var confirmed = Assert.Single(history, e => e.Action == "triage.confirmed");
        Assert.Equal("u-ben", confirmed.Actor.Id);
        Assert.Equal(recommendation.Id, confirmed.Details.GetProperty("recommendationId").GetGuid());
        Assert.Equal("IT", confirmed.Details.GetProperty("from").GetString());
        Assert.Equal("FAC", confirmed.Details.GetProperty("to").GetString());
        Assert.Equal(recommendation.Provider, confirmed.Details.GetProperty("provider").GetString());
        Assert.Contains("POL-ROUTE-003@2.1", confirmed.Details.GetProperty("policyRefs").EnumerateArray().Select(p => p.GetString()));
        Assert.Contains(history, e => e.Action == "routing.changed");

        await using var scope = api.Factory.Services.CreateAsyncScope();
        var db = scope.ServiceProvider.GetRequiredService<RequestHubDbContext>();
        var requestNumber = int.Parse(id[4..]);
        var requestRow = await db.Requests.SingleAsync(r => r.Number == requestNumber);
        var recipients = await db.Notifications.Where(n => n.RequestId == requestRow.Id && n.Type == "request.routed")
            .Select(n => n.Recipient).ToListAsync();
        Assert.Contains("u-ben", recipients);
    }

    [Fact]
    public async Task Admin_can_confirm_a_recommendation_for_accessible_departments()
    {
        var (id, recommendation) = await CreateRequestAndRecommendation();

        var response = await api.As("u-dan").PostAsync(
            $"/api/requests/{id}/triage-recommendations/{recommendation.Id}/confirm", null);

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.Equal("FAC", (await response.Read<RequestDetailDto>()).DepartmentId);
    }

    [Fact]
    public async Task Confirming_same_department_marks_recommendation_without_rerouting()
    {
        var (id, recommendation) = await CreateRequestAndRecommendation(title: "Replacement laptop for the field team", category: "equipment");
        Assert.Equal("IT", recommendation.SuggestedDepartmentId);

        var response = await api.As("u-ben").PostAsync(
            $"/api/requests/{id}/triage-recommendations/{recommendation.Id}/confirm", null);
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var detail = await response.Read<RequestDetailDto>();
        Assert.Equal("IT", detail.DepartmentId);
        Assert.Equal("Submitted", detail.Status);
        Assert.Equal("High", detail.Priority);
        var history = await (await api.As("u-ava").GetAsync($"/api/requests/{id}/history")).Read<List<AuditEventDto>>();
        Assert.Single(history, e => e.Action == "triage.confirmed");
        Assert.DoesNotContain(history, e => e.Action == "routing.changed");
    }

    [Fact]
    public async Task Requester_cannot_confirm_a_recommendation()
    {
        var (id, recommendation) = await CreateRequestAndRecommendation();
        var response = await api.As("u-ava").PostAsync(
            $"/api/requests/{id}/triage-recommendations/{recommendation.Id}/confirm", null);
        Assert.Equal(HttpStatusCode.Forbidden, response.StatusCode);
        Assert.Equal("auth.role_required", await response.Code());
        var history = await (await api.As("u-ava").GetAsync($"/api/requests/{id}/history")).Read<List<AuditEventDto>>();
        Assert.DoesNotContain(history, e => e.Action == "triage.confirmed");
    }

    [Fact]
    public async Task Reviewer_without_access_to_the_suggested_department_cannot_confirm()
    {
        var (id, recommendation) = await CreateRequestAndRecommendation();
        await ChangeSuggestedDepartment(id, recommendation.Id, "FIN");
        var response = await api.As("u-ben").PostAsync(
            $"/api/requests/{id}/triage-recommendations/{recommendation.Id}/confirm", null);
        Assert.Equal(HttpStatusCode.Forbidden, response.StatusCode);
        Assert.Equal("auth.department_forbidden", await response.Code());
        var history = await (await api.As("u-ava").GetAsync($"/api/requests/{id}/history")).Read<List<AuditEventDto>>();
        Assert.DoesNotContain(history, e => e.Action == "triage.confirmed");
    }

    [Fact]
    public async Task Reviewer_without_access_to_the_current_department_cannot_confirm()
    {
        var (id, recommendation) = await CreateRequestAndRecommendation("OPS", triagePersona: "u-dan");
        var response = await api.As("u-ben").PostAsync(
            $"/api/requests/{id}/triage-recommendations/{recommendation.Id}/confirm", null);
        Assert.Equal(HttpStatusCode.Forbidden, response.StatusCode);
        Assert.Equal("auth.department_forbidden", await response.Code());
    }

    [Fact]
    public async Task Superseded_recommendation_is_stale()
    {
        var (id, oldRecommendation) = await CreateRequestAndRecommendation();
        var second = await api.As("u-ben").PostAsync($"/api/requests/{id}/triage-recommendations", null);
        Assert.Equal(HttpStatusCode.Created, second.StatusCode);

        var response = await api.As("u-ben").PostAsync(
            $"/api/requests/{id}/triage-recommendations/{oldRecommendation.Id}/confirm", null);
        Assert.Equal(HttpStatusCode.Conflict, response.StatusCode);
        Assert.Equal("recommendation.stale", await response.Code());
        var history = await (await api.As("u-ava").GetAsync($"/api/requests/{id}/history")).Read<List<AuditEventDto>>();
        Assert.DoesNotContain(history, e => e.Action == "triage.confirmed");
    }

    [Fact]
    public async Task Recommendation_is_stale_after_request_department_changes()
    {
        var (id, recommendation) = await CreateRequestAndRecommendation();
        var reroute = await api.As("u-ben").PutAsJsonAsync($"/api/requests/{id}/routing", new { departmentId = "FAC", reason = "Changed by reviewer" });
        Assert.Equal(HttpStatusCode.OK, reroute.StatusCode);

        var response = await api.As("u-ben").PostAsync(
            $"/api/requests/{id}/triage-recommendations/{recommendation.Id}/confirm", null);
        Assert.Equal(HttpStatusCode.Conflict, response.StatusCode);
        Assert.Equal("recommendation.stale", await response.Code());
        var history = await (await api.As("u-ava").GetAsync($"/api/requests/{id}/history")).Read<List<AuditEventDto>>();
        Assert.DoesNotContain(history, e => e.Action == "triage.confirmed");
    }

    [Fact]
    public async Task Duplicate_confirmation_conflicts_without_a_second_audit()
    {
        var (id, recommendation) = await CreateRequestAndRecommendation();
        var path = $"/api/requests/{id}/triage-recommendations/{recommendation.Id}/confirm";
        Assert.Equal(HttpStatusCode.OK, (await api.As("u-ben").PostAsync(path, null)).StatusCode);
        var duplicate = await api.As("u-ben").PostAsync(path, null);
        Assert.Equal(HttpStatusCode.Conflict, duplicate.StatusCode);
        Assert.Equal("recommendation.already_confirmed", await duplicate.Code());

        var history = await (await api.As("u-ava").GetAsync($"/api/requests/{id}/history")).Read<List<AuditEventDto>>();
        Assert.Single(history, e => e.Action == "triage.confirmed");
    }

    [Fact]
    public async Task Concurrent_confirmation_clicks_record_one_confirmation()
    {
        var (id, recommendation) = await CreateRequestAndRecommendation();
        var path = $"/api/requests/{id}/triage-recommendations/{recommendation.Id}/confirm";
        var attempts = await Task.WhenAll(Enumerable.Range(0, 6)
            .Select(_ => api.As("u-ben").PostAsync(path, null)));

        Assert.Single(attempts, response => response.StatusCode == HttpStatusCode.OK);
        foreach (var response in attempts.Where(response => response.StatusCode != HttpStatusCode.OK))
        {
            Assert.Equal(HttpStatusCode.Conflict, response.StatusCode);
            Assert.Equal("recommendation.already_confirmed", await response.Code());
        }
        var history = await (await api.As("u-ava").GetAsync($"/api/requests/{id}/history")).Read<List<AuditEventDto>>();
        Assert.Single(history, e => e.Action == "triage.confirmed");
    }

    [Theory]
    [InlineData("Approved")]
    [InlineData("Rejected")]
    public async Task Terminal_request_cannot_confirm_recommendation(string outcome)
    {
        var (id, recommendation) = await CreateRequestAndRecommendation();
        var decision = await api.As("u-chloe").PostJson($"/api/requests/{id}/decisions",
            new { outcome, comment = outcome == "Rejected" ? "Not required." : null });
        Assert.Equal(HttpStatusCode.Created, decision.StatusCode);

        var response = await api.As("u-ben").PostAsync(
            $"/api/requests/{id}/triage-recommendations/{recommendation.Id}/confirm", null);
        Assert.Equal(HttpStatusCode.Conflict, response.StatusCode);
        Assert.Equal("request.terminal", await response.Code());
        var history = await (await api.As("u-ava").GetAsync($"/api/requests/{id}/history")).Read<List<AuditEventDto>>();
        Assert.DoesNotContain(history, e => e.Action == "triage.confirmed");
    }

    private async Task ChangeSuggestedDepartment(string requestId, Guid recommendationId, string departmentId)
    {
        await using var scope = api.Factory.Services.CreateAsyncScope();
        var db = scope.ServiceProvider.GetRequiredService<RequestHubDbContext>();
        var requestNumber = int.Parse(requestId[4..]);
        var request = await db.Requests.SingleAsync(r => r.Number == requestNumber);
        var recommendation = await db.Recommendations.SingleAsync(r => r.RequestId == request.Id && r.Id == recommendationId);
        recommendation.SuggestedDepartmentId = departmentId;
        await db.SaveChangesAsync();
    }
}
