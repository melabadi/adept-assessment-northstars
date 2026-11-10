using System.Net;
using System.Text.Json;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using RequestHub.Core.Data;
using RequestHub.Core.Services;

namespace RequestHub.Tests;

public sealed class DuplicateDecisionTests(ApiFixture api) : IClassFixture<ApiFixture>
{
    private static object NewRequest(string title) => new
    {
        title,
        description = "USB-C dock needed for the shared desk in the north wing.",
        category = "equipment",
        departmentId = "IT",
        priority = "Normal",
    };

    private async Task<string> SubmitRequestAsync()
    {
        var response = await api.As("u-ava").PostJson("/api/requests", NewRequest($"Dock {Guid.NewGuid():N}"));
        Assert.Equal(HttpStatusCode.Created, response.StatusCode);
        return (await response.Read<RequestDetailDto>()).Id;
    }

    private async Task AssertSingleDecisionAndNotificationAsync(string id)
    {
        var history = await (await api.As("u-ava").GetAsync($"/api/requests/{id}/history")).Read<List<AuditEventDto>>();
        Assert.Single(history, e => e.Action == "decision.recorded");

        await using var scope = api.Factory.Services.CreateAsyncScope();
        var db = scope.ServiceProvider.GetRequiredService<RequestHubDbContext>();
        var requestNumber = int.Parse(id.AsSpan("REQ-".Length));
        var requestId = await db.Requests.Where(r => r.Number == requestNumber).Select(r => r.Id).SingleAsync();
        Assert.Equal(1, await db.Notifications.CountAsync(n => n.RequestId == requestId && n.Type == "request.decided"));
    }

    [Fact]
    public async Task Same_approver_retry_returns_existing_decision_without_duplicate_side_effects()
    {
        var id = await SubmitRequestAsync();
        using var chloe = api.As("u-chloe");
        var first = await chloe.PostJson($"/api/requests/{id}/decisions", new { outcome = "Approved" }, "approve-once");
        var retry = await chloe.PostJson($"/api/requests/{id}/decisions", new { outcome = "Approved" }, "approve-once");

        Assert.Equal(HttpStatusCode.Created, first.StatusCode);
        Assert.Equal(HttpStatusCode.OK, retry.StatusCode);
        var firstDecision = await first.Read<DecisionDto>();
        var replayedDecision = await retry.Read<DecisionDto>();
        Assert.Equal(firstDecision.Outcome, replayedDecision.Outcome);
        Assert.Equal(firstDecision.DecidedBy, replayedDecision.DecidedBy);
        Assert.Equal(firstDecision.Comment, replayedDecision.Comment);
        await AssertSingleDecisionAndNotificationAsync(id);
    }

    [Fact]
    public async Task Different_approver_cannot_change_a_decision_and_receives_the_existing_decision()
    {
        var id = await SubmitRequestAsync();
        var first = await api.As("u-chloe").PostJson($"/api/requests/{id}/decisions", new { outcome = "Approved" });
        var later = await api.As("u-dan").PostJson($"/api/requests/{id}/decisions", new { outcome = "Rejected", comment = "Changed my mind" });

        Assert.Equal(HttpStatusCode.Created, first.StatusCode);
        Assert.Equal(HttpStatusCode.Conflict, later.StatusCode);
        Assert.Equal("decision.already_decided", await later.Code());
        using (var response = JsonDocument.Parse(await later.Content.ReadAsStringAsync()))
        {
            var existing = response.RootElement.GetProperty("decision");
            Assert.Equal("Approved", existing.GetProperty("outcome").GetString());
            Assert.Equal("u-chloe", existing.GetProperty("decidedBy").GetProperty("id").GetString());
        }

        var detail = await (await api.As("u-ava").GetAsync($"/api/requests/{id}")).Read<RequestDetailDto>();
        Assert.Equal("Approved", detail.Status);
        Assert.Equal("u-chloe", detail.Decision!.DecidedBy.Id);
        await AssertSingleDecisionAndNotificationAsync(id);
    }

    [Fact]
    public async Task Concurrent_decisions_have_one_winner_idempotent_replays_and_no_duplicate_side_effects()
    {
        var id = await SubmitRequestAsync();
        using var chloe = api.As("u-chloe");
        using var dan = api.As("u-dan");
        var calls = Enumerable.Range(0, 8).Select(index =>
        {
            var sameApproverRetry = index < 4;
            var client = sameApproverRetry ? chloe : dan;
            var key = sameApproverRetry ? "concurrent-approve" : "concurrent-reject";
            var body = sameApproverRetry
                ? new { outcome = "Approved", comment = (string?)null }
                : new { outcome = "Rejected", comment = (string?)"Changed my mind" };
            return client.PostJson($"/api/requests/{id}/decisions", body, key);
        });

        var responses = await Task.WhenAll(calls);
        Assert.Equal(1, responses.Count(r => r.StatusCode == HttpStatusCode.Created));
        Assert.Equal(3, responses.Count(r => r.StatusCode == HttpStatusCode.OK));
        Assert.Equal(4, responses.Count(r => r.StatusCode == HttpStatusCode.Conflict));
        foreach (var conflict in responses.Where(r => r.StatusCode == HttpStatusCode.Conflict))
        {
            Assert.Equal("decision.already_decided", await conflict.Code());
        }

        var detail = await (await api.As("u-ava").GetAsync($"/api/requests/{id}")).Read<RequestDetailDto>();
        Assert.Equal(detail.Decision!.Outcome, detail.Status);
        Assert.Contains(detail.Decision.DecidedBy.Id, new[] { "u-chloe", "u-dan" });
        await AssertSingleDecisionAndNotificationAsync(id);
    }
}
