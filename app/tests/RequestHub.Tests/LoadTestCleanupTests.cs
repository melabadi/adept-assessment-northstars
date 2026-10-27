using System.Net;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using RequestHub.Core.Data;
using RequestHub.Core.Services;

namespace RequestHub.Tests;

public sealed class LoadTestCleanupFixture : ApiFixture
{
    // u-ben and u-chloe play the load-test identities in this isolated database; neither owns a seeded request.
    protected override IReadOnlyDictionary<string, string> Settings { get; } = new Dictionary<string, string> { ["Demo:LoadTestRequesterIds"] = "u-ben, u-chloe" };
}

public sealed class LoadTestCleanupTests(LoadTestCleanupFixture api) : IClassFixture<LoadTestCleanupFixture>
{
    private async Task<string> Submit(string persona, string title)
    {
        var response = await api.As(persona).PostJson("/api/requests", new { title, description = "Synthetic load-test request.", category = "equipment", departmentId = "IT" });
        Assert.Equal(HttpStatusCode.Created, response.StatusCode);
        return (await response.Read<RequestDetailDto>()).Id;
    }

    private async Task<HttpStatusCode> Open(string id) => (await api.As("u-dan").GetAsync($"/api/requests/{id}")).StatusCode;

    [Fact]
    public async Task Admin_cleanup_deletes_only_requests_owned_by_load_test_identities()
    {
        var ben = await Submit("u-ben", "Load test request A");
        var chloe = await Submit("u-chloe", "Load test request B");
        var kept = await Submit("u-ava", "Real request that must be kept");
        // The decision, its audit entry, and its notification belong to the load-test request and go with it.
        Assert.Equal(HttpStatusCode.Created, (await api.As("u-chloe").PostJson($"/api/requests/{ben}/decisions", new { outcome = "Approved" })).StatusCode);

        var response = await api.As("u-dan").PostAsync("/api/admin/load-test/cleanup", new StringContent(""));
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var result = await response.Read<LoadTestCleanupDto>();
        Assert.True(result.Deleted >= 2);
        Assert.Equal(["u-ben", "u-chloe"], result.Owners);

        Assert.Equal(HttpStatusCode.NotFound, await Open(ben));
        Assert.Equal(HttpStatusCode.NotFound, await Open(chloe));
        Assert.Equal(HttpStatusCode.OK, await Open(kept));

        using var scope = api.Factory.Services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<RequestHubDbContext>();
        var seeded = RequestHubDbContext.FirstRequestNumber + DemoSeeder.SeedRequestCount;
        Assert.Equal(DemoSeeder.SeedRequestCount, await db.Requests.CountAsync(r => r.Number < seeded));
        Assert.False(await db.Requests.AnyAsync(r => r.RequesterId == "u-ben" || r.RequesterId == "u-chloe"));
        Assert.False(await db.AuditEvents.AnyAsync(a => a.RequestId != null && !db.Requests.Any(r => r.Id == a.RequestId)));
        Assert.False(await db.Notifications.AnyAsync(n => n.RequestId != null && !db.Requests.Any(r => r.Id == n.RequestId)));
        Assert.True(await db.AuditEvents.AnyAsync(a => a.Action == "loadtest.cleanup" && a.Actor == "u-dan" && a.RequestId == null));
    }

    [Fact]
    public async Task A_load_test_identity_cleans_up_only_its_own_requests()
    {
        var ben = await Submit("u-ben", "Load test request C");
        var chloe = await Submit("u-chloe", "Load test request D");

        var response = await api.As("u-ben").PostAsync("/api/admin/load-test/cleanup", new StringContent(""));
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.Equal(["u-ben"], (await response.Read<LoadTestCleanupDto>()).Owners);

        Assert.Equal(HttpStatusCode.NotFound, await Open(ben));
        Assert.Equal(HttpStatusCode.OK, await Open(chloe));
        Assert.Equal(HttpStatusCode.OK, await Open("REQ-1002"));
    }

    [Theory]
    [InlineData("u-ava")]
    [InlineData("u-grace")]
    public async Task Callers_who_are_neither_admin_nor_a_load_test_identity_are_refused(string persona)
    {
        var loadTestRequest = await Submit("u-ben", "Load test request E");

        var response = await api.As(persona).PostAsync("/api/admin/load-test/cleanup", new StringContent(""));
        Assert.Equal(HttpStatusCode.Forbidden, response.StatusCode);
        Assert.Equal("demo.load_test_cleanup_forbidden", await response.Code());
        Assert.Equal(HttpStatusCode.OK, await Open(loadTestRequest));
    }

    [Fact]
    public async Task Anonymous_cleanup_is_rejected()
    {
        var client = api.Factory.CreateClient();
        client.DefaultRequestHeaders.Add("X-RequestHub-Client", "tests");
        var response = await client.PostAsync("/api/admin/load-test/cleanup", new StringContent(""));
        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
    }
}

public sealed class LoadTestCleanupDisabledTests(ApiFixture api) : IClassFixture<ApiFixture>
{
    [Fact]
    public async Task Cleanup_is_refused_when_no_load_test_identity_is_configured()
    {
        var response = await api.As("u-dan").PostAsync("/api/admin/load-test/cleanup", new StringContent(""));
        Assert.Equal(HttpStatusCode.Forbidden, response.StatusCode);
        Assert.Equal("demo.load_test_cleanup_disabled", await response.Code());
    }
}
