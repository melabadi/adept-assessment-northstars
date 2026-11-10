using System.Net;
using System.Text.Json;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using RequestHub.Core.Data;
using RequestHub.Core.Services;

namespace RequestHub.Tests;

public sealed class DuplicateDecisionTests(ApiFixture api) : IClassFixture<ApiFixture>
{
    private async Task<string> CreateAsync()
    {
        var response = await api.As("u-ava").PostJson("/api/requests", new
        {
            title = "Duplicate decision regression",
            description = "Equipment needed for the shared desk in the north wing.",
            category = "equipment",
            departmentId = "IT",
        });
        Assert.Equal(HttpStatusCode.Created, response.StatusCode);
        return (await response.Read<RequestDetailDto>()).Id;
    }

    private Task<HttpResponseMessage> DecideAsync(string id, string user = "u-chloe", string? key = null,
        string outcome = "Approved", string comment = "Within catalogue.") =>
        api.As(user).PostJson($"/api/requests/{id}/decisions", new { outcome, comment }, key);

    private static async Task AssertConflictAsync(HttpResponseMessage response, DecisionDto original)
    {
        Assert.Equal(HttpStatusCode.Conflict, response.StatusCode);
        var problem = await response.Read<JsonElement>();
        Assert.Equal("decision.already_decided", problem.GetProperty("code").GetString());
        AssertOriginal(original, problem.GetProperty("decision").Deserialize<DecisionDto>(ApiFixture.Json)!);
    }

    private static void AssertOriginal(DecisionDto original, DecisionDto actual)
    {
        Assert.Equal(original.Outcome, actual.Outcome);
        Assert.Equal(original.DecidedBy, actual.DecidedBy);
        Assert.Equal(original.Comment, actual.Comment);
        // PostgreSQL stores timestamps at microsecond precision.
        Assert.Equal(original.DecidedAt.Ticks / 10, actual.DecidedAt.Ticks / 10);
    }

    private async Task AssertSingleDecisionAsync(string id, DecisionDto original)
    {
        var detail = await (await api.As("u-ava").GetAsync($"/api/requests/{id}")).Read<RequestDetailDto>();
        Assert.Equal(original.Outcome, detail.Status);
        AssertOriginal(original, Assert.IsType<DecisionDto>(detail.Decision));
        var history = await (await api.As("u-ava").GetAsync($"/api/requests/{id}/history")).Read<List<AuditEventDto>>();
        Assert.Equal(original.DecidedBy.Id, Assert.Single(history, e => e.Action == "decision.recorded").Actor.Id);

        using var scope = api.Factory.Services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<RequestHubDbContext>();
        var number = int.Parse(id[4..]);
        var request = await db.Requests.SingleAsync(r => r.Number == number);
        Assert.Equal(1, await db.Decisions.CountAsync(d => d.RequestId == request.Id));
        var notification = Assert.Single(await db.Notifications
            .Where(n => n.RequestId == request.Id && n.Type == "request.decided").ToListAsync());
        Assert.Equal("u-ava", notification.Recipient);
    }

    [Theory]
    [InlineData("u-dan", null)]
    [InlineData("u-dan", "first-click")]
    [InlineData("u-chloe", "different-click")]
    [InlineData("u-chloe", null)]
    public async Task Decision_later_attempt_conflicts_and_preserves_first(string user, string? laterKey)
    {
        var id = await CreateAsync();
        var first = await DecideAsync(id, key: "first-click");
        Assert.Equal(HttpStatusCode.Created, first.StatusCode);
        var original = await first.Read<DecisionDto>();
        await AssertConflictAsync(await DecideAsync(id, user, laterKey, "Rejected", "Not needed."), original);
        await AssertSingleDecisionAsync(id, original);
    }

    [Fact]
    public async Task Decision_same_user_same_key_replays_original_even_with_changed_payload()
    {
        var id = await CreateAsync();
        var first = await DecideAsync(id, key: "first-click");
        Assert.Equal(HttpStatusCode.Created, first.StatusCode);
        var original = await first.Read<DecisionDto>();
        var retry = await DecideAsync(id, key: "first-click", outcome: "Rejected", comment: "Changed payload.");
        Assert.Equal(HttpStatusCode.OK, retry.StatusCode);
        AssertOriginal(original, await retry.Read<DecisionDto>());
        await AssertSingleDecisionAsync(id, original);
    }

    [Theory]
    [InlineData(null)]
    [InlineData("shared-click")]
    public async Task Decision_eight_concurrent_clicks_record_exactly_one(string? key)
    {
        var id = await CreateAsync();
        var responses = await Task.WhenAll(Enumerable.Range(0, 8).Select(_ => DecideAsync(id, key: key)));
        var first = Assert.Single(responses, r => r.StatusCode == HttpStatusCode.Created);
        var original = await first.Read<DecisionDto>();
        foreach (var response in responses.Where(r => r != first))
        {
            if (key is null)
                await AssertConflictAsync(response, original);
            else
            {
                Assert.Equal(HttpStatusCode.OK, response.StatusCode);
                AssertOriginal(original, await response.Read<DecisionDto>());
            }
        }
        await AssertSingleDecisionAsync(id, original);
    }

    [Fact]
    public async Task Decision_two_approvers_competing_with_same_key_first_wins()
    {
        var id = await CreateAsync();
        var responses = await Task.WhenAll(
            DecideAsync(id, key: "shared-click"),
            DecideAsync(id, "u-dan", "shared-click", "Rejected", "Not needed."));
        var first = Assert.Single(responses, r => r.StatusCode == HttpStatusCode.Created);
        var original = await first.Read<DecisionDto>();
        await AssertConflictAsync(Assert.Single(responses, r => r != first), original);
        await AssertSingleDecisionAsync(id, original);
    }

    [Theory]
    [InlineData("u-ben", "decision.not_approver")]
    [InlineData("u-grace", "auth.department_forbidden")]
    public async Task Decision_existing_result_does_not_bypass_authorization(string user, string code)
    {
        var id = await CreateAsync();
        var first = await DecideAsync(id, key: "shared-click");
        Assert.Equal(HttpStatusCode.Created, first.StatusCode);
        var response = await DecideAsync(id, user, "shared-click");
        Assert.Equal(HttpStatusCode.Forbidden, response.StatusCode);
        Assert.Equal(code, await response.Code());
        await AssertSingleDecisionAsync(id, await first.Read<DecisionDto>());
    }
}
