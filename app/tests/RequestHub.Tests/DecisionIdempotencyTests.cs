using System.Net;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using RequestHub.Core.Data;
using RequestHub.Core.Services;

namespace RequestHub.Tests;

public sealed class DecisionIdempotencyTests(ApiFixture api) : IClassFixture<ApiFixture>
{
    private static object NewRequest(string title) => new
    {
        title,
        description = "Adjustable monitor arm for the shared office desk.",
        category = "equipment",
        departmentId = "IT",
    };

    private async Task<string> SubmitRequest(string title)
    {
        var response = await api.As("u-ava").PostJson("/api/requests", NewRequest(title));
        Assert.Equal(HttpStatusCode.Created, response.StatusCode);
        return (await response.Read<RequestDetailDto>()).Id;
    }

    private async Task<(int Decisions, int AuditEvents, int Notifications)> DecisionArtifacts(string id)
    {
        using var scope = api.Factory.Services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<RequestHubDbContext>();
        var number = int.Parse(id[4..]);
        var requestId = await db.Requests.Where(r => r.Number == number).Select(r => r.Id).SingleAsync();
        return (
            await db.Decisions.CountAsync(d => d.RequestId == requestId),
            await db.AuditEvents.CountAsync(e => e.RequestId == requestId && e.Action == "decision.recorded"),
            await db.Notifications.CountAsync(n => n.RequestId == requestId && n.Type == "request.decided" && n.Recipient == "u-ava"));
    }

    [Fact]
    public async Task Same_user_retry_with_same_idempotency_key_returns_original_decision_once()
    {
        var id = await SubmitRequest("Decision retry request");
        var chloe = api.As("u-chloe");
        const string key = "decision-retry-key";

        var first = await chloe.PostJson($"/api/requests/{id}/decisions", new { outcome = "Approved", comment = "Original decision" }, key);
        var retry = await chloe.PostJson($"/api/requests/{id}/decisions", new { outcome = "Approved", comment = "Original decision" }, key);

        Assert.Equal(HttpStatusCode.Created, first.StatusCode);
        Assert.Equal(HttpStatusCode.OK, retry.StatusCode);
        var originalDecision = await first.Read<DecisionDto>();
        var replayedDecision = await retry.Read<DecisionDto>();
        Assert.Equal(originalDecision.Outcome, replayedDecision.Outcome);
        Assert.Equal(originalDecision.DecidedBy.Id, replayedDecision.DecidedBy.Id);
        Assert.InRange(
            Math.Abs((replayedDecision.DecidedAt - originalDecision.DecidedAt).Ticks),
            0,
            TimeSpan.TicksPerMillisecond);
        Assert.Equal((1, 1, 1), await DecisionArtifacts(id));
    }

    [Fact]
    public async Task Other_approver_cannot_replace_existing_decision_or_duplicate_its_artifacts()
    {
        var id = await SubmitRequest("Competing decision request");
        var first = await api.As("u-chloe").PostJson($"/api/requests/{id}/decisions", new { outcome = "Approved", comment = "Approved as submitted" });
        Assert.Equal(HttpStatusCode.Created, first.StatusCode);

        var competing = await api.As("u-dan").PostJson($"/api/requests/{id}/decisions", new { outcome = "Rejected", comment = "Changed my mind" });

        Assert.Equal(HttpStatusCode.Conflict, competing.StatusCode);
        var problem = await competing.Read<System.Text.Json.JsonElement>();
        Assert.Equal("decision.already_decided", problem.GetProperty("code").GetString());
        Assert.Equal("Approved", problem.GetProperty("decision").GetProperty("outcome").GetString());
        Assert.Equal("u-chloe", problem.GetProperty("decision").GetProperty("decidedBy").GetProperty("id").GetString());

        var detail = await (await api.As("u-ava").GetAsync($"/api/requests/{id}")).Read<RequestDetailDto>();
        Assert.Equal("Approved", detail.Status);
        Assert.Equal("u-chloe", detail.Decision!.DecidedBy.Id);
        var history = await (await api.As("u-ava").GetAsync($"/api/requests/{id}/history")).Read<List<AuditEventDto>>();
        Assert.Single(history, item => item.Action == "decision.recorded");
        Assert.Equal((1, 1, 1), await DecisionArtifacts(id));
    }

    [Fact]
    public async Task Concurrent_approvals_record_one_decision_and_return_conflict_for_the_rest()
    {
        var id = await SubmitRequest("Concurrent decision request");
        var chloe = api.As("u-chloe");

        var responses = await Task.WhenAll(Enumerable.Range(0, 8)
            .Select(_ => chloe.PostJson($"/api/requests/{id}/decisions", new { outcome = "Approved" })));

        Assert.Equal(1, responses.Count(response => response.StatusCode == HttpStatusCode.Created));
        Assert.Equal(7, responses.Count(response => response.StatusCode == HttpStatusCode.Conflict));
        foreach (var response in responses.Where(response => response.StatusCode == HttpStatusCode.Conflict))
        {
            Assert.Equal("decision.already_decided", await response.Code());
        }
        Assert.DoesNotContain(responses, response => response.StatusCode == HttpStatusCode.InternalServerError);

        var detail = await (await api.As("u-ava").GetAsync($"/api/requests/{id}")).Read<RequestDetailDto>();
        Assert.Equal("Approved", detail.Status);
        Assert.Equal("u-chloe", detail.Decision!.DecidedBy.Id);
        var history = await (await api.As("u-ava").GetAsync($"/api/requests/{id}/history")).Read<List<AuditEventDto>>();
        Assert.Single(history, item => item.Action == "decision.recorded");
        Assert.Equal((1, 1, 1), await DecisionArtifacts(id));
    }
}
