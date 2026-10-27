using System.Net;
using System.Text.Json;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using RequestHub.Core.Data;
using RequestHub.Core.Services;

namespace RequestHub.Tests;

public sealed class RequestLifecycleTests(ApiFixture api) : IClassFixture<ApiFixture>
{
    private static object NewRequest(string title = "Docking station for desk 9C") => new
    {
        title,
        description = "USB-C dock needed for the shared desk in the north wing.",
        category = "equipment",
        departmentId = "IT",
        priority = "Normal",
    };

    [Fact]
    public async Task Created_request_appears_in_list_and_detail_with_same_values()
    {
        var ava = api.As("u-ava");
        var created = await ava.PostJson("/api/requests", NewRequest("Monitor arm for desk 7A"));
        Assert.Equal(HttpStatusCode.Created, created.StatusCode);
        var detail = await created.Read<RequestDetailDto>();
        Assert.StartsWith("REQ-", detail.Id);
        Assert.Equal("Submitted", detail.Status);

        var mine = await (await ava.GetAsync("/api/requests?scope=mine&pageSize=100")).Read<PagedResult<RequestSummaryDto>>();
        var row = Assert.Single(mine.Items, r => r.Id == detail.Id);
        Assert.Equal(detail.Title, row.Title);
        Assert.Equal(detail.DepartmentId, row.DepartmentId);

        var fetched = await (await ava.GetAsync($"/api/requests/{detail.Id}")).Read<RequestDetailDto>();
        Assert.Equal(detail.Title, fetched.Title);
        Assert.Equal("u-ava", fetched.Requester.Id);
    }

    [Fact]
    public async Task Create_with_same_idempotency_key_returns_the_original_request()
    {
        var ava = api.As("u-ava");
        var first = await ava.PostJson("/api/requests", NewRequest("Keyboard tray"), "create-key-1");
        var retry = await ava.PostJson("/api/requests", NewRequest("Keyboard tray"), "create-key-1");
        Assert.Equal(HttpStatusCode.Created, first.StatusCode);
        Assert.Equal(HttpStatusCode.OK, retry.StatusCode);
        Assert.Equal((await first.Read<RequestDetailDto>()).Id, (await retry.Read<RequestDetailDto>()).Id);
    }

    [Fact]
    public async Task Invalid_input_is_rejected_with_validation_code()
    {
        var response = await api.As("u-ava").PostJson("/api/requests", new { title = "x", description = "short", category = "equipment", departmentId = "IT" });
        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
        Assert.Equal("validation.failed", await response.Code());
    }

    [Fact]
    public async Task Approver_decision_is_recorded_in_status_and_history()
    {
        var id = (await (await api.As("u-ava").PostJson("/api/requests", NewRequest("Webcam for hybrid meetings"))).Read<RequestDetailDto>()).Id;
        var decision = await api.As("u-chloe").PostJson($"/api/requests/{id}/decisions", new { outcome = "Approved", comment = "Within catalogue." });
        Assert.Equal(HttpStatusCode.Created, decision.StatusCode);

        var detail = await (await api.As("u-ava").GetAsync($"/api/requests/{id}")).Read<RequestDetailDto>();
        Assert.Equal("Approved", detail.Status);
        Assert.Equal("u-chloe", detail.Decision!.DecidedBy.Id);

        var history = await (await api.As("u-ava").GetAsync($"/api/requests/{id}/history")).Read<List<AuditEventDto>>();
        Assert.Contains(history, e => e.Action == "decision.recorded" && e.Actor.Id == "u-chloe");
    }

    [Fact]
    public async Task Decision_retry_with_same_idempotency_key_returns_original_without_duplicate_side_effects()
    {
        var id = (await (await api.As("u-ava").PostJson("/api/requests", NewRequest("Headset for support desk"))).Read<RequestDetailDto>()).Id;
        var approver = api.As("u-chloe");

        var first = await approver.PostJson($"/api/requests/{id}/decisions", new { outcome = "Approved", comment = "Within catalogue." }, "decision-key-1");
        var retry = await approver.PostJson($"/api/requests/{id}/decisions", new { outcome = "Approved", comment = "Within catalogue." }, "decision-key-1");

        Assert.Equal(HttpStatusCode.Created, first.StatusCode);
        Assert.Equal(HttpStatusCode.OK, retry.StatusCode);
        Assert.Equal(await first.Read<DecisionDto>(), await retry.Read<DecisionDto>());
        await AssertSingleDecisionSideEffects(id);
    }

    [Fact]
    public async Task Later_approver_decision_returns_conflict_and_preserves_first_decision()
    {
        var id = (await (await api.As("u-ava").PostJson("/api/requests", NewRequest("Replacement webcam"))).Read<RequestDetailDto>()).Id;
        var first = await api.As("u-chloe").PostJson($"/api/requests/{id}/decisions", new { outcome = "Approved", comment = "Within catalogue." });

        var second = await api.As("u-dan").PostJson($"/api/requests/{id}/decisions", new { outcome = "Rejected", comment = "Changed my mind." });

        Assert.Equal(HttpStatusCode.Created, first.StatusCode);
        Assert.Equal(HttpStatusCode.Conflict, second.StatusCode);
        var conflict = await second.Read<JsonElement>();
        Assert.Equal("decision.already_decided", conflict.GetProperty("code").GetString());
        Assert.Equal("Approved", conflict.GetProperty("decision").GetProperty("outcome").GetString());

        var detail = await (await api.As("u-ava").GetAsync($"/api/requests/{id}")).Read<RequestDetailDto>();
        Assert.Equal("Approved", detail.Status);
        Assert.Equal("u-chloe", detail.Decision!.DecidedBy.Id);
        await AssertSingleDecisionSideEffects(id);
    }

    [Fact]
    public async Task Concurrent_decision_retries_with_same_idempotency_key_return_original_without_duplicate_side_effects()
    {
        var id = (await (await api.As("u-ava").PostJson("/api/requests", NewRequest("Wireless mouse"))).Read<RequestDetailDto>()).Id;
        var approver = api.As("u-chloe");

        var responses = await Task.WhenAll(Enumerable.Range(0, 8)
            .Select(_ => approver.PostJson($"/api/requests/{id}/decisions", new { outcome = "Approved" }, "decision-key-concurrent")));

        Assert.Equal(1, responses.Count(r => r.StatusCode == HttpStatusCode.Created));
        Assert.Equal(7, responses.Count(r => r.StatusCode == HttpStatusCode.OK));
        var decisions = await Task.WhenAll(responses.Select(response => response.Read<DecisionDto>()));
        var originalDecision = decisions[Array.FindIndex(responses, r => r.StatusCode == HttpStatusCode.Created)];
        Assert.All(decisions, decision => Assert.Equal(originalDecision, decision));

        await AssertSingleDecisionSideEffects(id);
    }

    [Fact]
    public async Task Concurrent_approvals_record_one_decision_and_return_conflicts_for_the_rest()
    {
        var id = (await (await api.As("u-ava").PostJson("/api/requests", NewRequest("USB-C charger"))).Read<RequestDetailDto>()).Id;
        var approver = api.As("u-chloe");

        var responses = await Task.WhenAll(Enumerable.Range(0, 8)
            .Select(_ => approver.PostJson($"/api/requests/{id}/decisions", new { outcome = "Approved" })));

        Assert.Equal(1, responses.Count(r => r.StatusCode == HttpStatusCode.Created));
        Assert.Equal(7, responses.Count(r => r.StatusCode == HttpStatusCode.Conflict));
        foreach (var response in responses.Where(r => r.StatusCode == HttpStatusCode.Conflict))
        {
            Assert.Equal("decision.already_decided", await response.Code());
        }

        var detail = await (await api.As("u-ava").GetAsync($"/api/requests/{id}")).Read<RequestDetailDto>();
        Assert.Equal("Approved", detail.Status);
        Assert.Equal("u-chloe", detail.Decision!.DecidedBy.Id);
        await AssertSingleDecisionSideEffects(id);
    }

    private async Task AssertSingleDecisionSideEffects(string requestId)
    {
        var history = await (await api.As("u-ava").GetAsync($"/api/requests/{requestId}/history")).Read<List<AuditEventDto>>();
        Assert.Single(history, e => e.Action == "decision.recorded");

        await using var scope = api.Factory.Services.CreateAsyncScope();
        var db = scope.ServiceProvider.GetRequiredService<RequestHubDbContext>();
        var notifications = await db.Notifications
            .Where(n => n.Type == "request.decided" && n.Recipient == "u-ava")
            .ToListAsync();
        Assert.Single(notifications, n => n.Payload.Contains(requestId));
    }

    [Fact]
    public async Task Requester_cannot_approve_their_own_request()
    {
        // Hugo is an IT approver and the requester of REQ-1024.
        var response = await api.As("u-hugo").PostJson("/api/requests/REQ-1024/decisions", new { outcome = "Approved" });
        Assert.Equal(HttpStatusCode.Forbidden, response.StatusCode);
        Assert.Equal("decision.self_approval", await response.Code());
    }

    [Fact]
    public async Task Reviewer_without_approver_role_cannot_decide()
    {
        var response = await api.As("u-ben").PostJson("/api/requests/REQ-1002/decisions", new { outcome = "Approved" });
        Assert.Equal(HttpStatusCode.Forbidden, response.StatusCode);
        Assert.Equal("decision.not_approver", await response.Code());
    }

    [Fact]
    public async Task Rejection_requires_a_comment()
    {
        var response = await api.As("u-chloe").PostJson("/api/requests/REQ-1009/decisions", new { outcome = "Rejected" });
        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
    }

    [Fact]
    public async Task Decided_request_cannot_be_rerouted()
    {
        var response = await api.As("u-ben").SendAsync(new HttpRequestMessage(HttpMethod.Put, "/api/requests/REQ-1004/routing")
        {
            Content = System.Net.Http.Json.JsonContent.Create(new { departmentId = "IT", reason = "test" }),
        });
        Assert.Equal(HttpStatusCode.Conflict, response.StatusCode);
        Assert.Equal("request.terminal", await response.Code());
    }

    [Fact]
    public async Task Reviewer_reroute_is_audited_and_moves_request_to_review()
    {
        var id = (await (await api.As("u-ava").PostJson("/api/requests", NewRequest("Desk lamp for night shift"))).Read<RequestDetailDto>()).Id;
        var response = await api.As("u-ben").SendAsync(new HttpRequestMessage(HttpMethod.Put, $"/api/requests/{id}/routing")
        {
            Content = System.Net.Http.Json.JsonContent.Create(new { departmentId = "FAC", reason = "Lighting is a workplace item" }),
        });
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var detail = await response.Read<RequestDetailDto>();
        Assert.Equal("FAC", detail.DepartmentId);
        Assert.Equal("InReview", detail.Status);
        var history = await (await api.As("u-ava").GetAsync($"/api/requests/{id}/history")).Read<List<AuditEventDto>>();
        Assert.Contains(history, e => e.Action == "routing.changed");
    }
}
