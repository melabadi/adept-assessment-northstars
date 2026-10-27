using System.Net;
using RequestHub.Core.Services;

namespace RequestHub.Tests;

public sealed class SearchSecurityTests(ApiFixture api) : IClassFixture<ApiFixture>
{
    [Theory]
    [InlineData("u-ava", "mine", "' OR '1'='1")]
    [InlineData("u-ben", "queue", "' OR '1'='1")]
    [InlineData("u-dan", "all", "' OR '1'='1")]
    [InlineData("u-ava", "mine", "quote'")]
    [InlineData("u-ben", "queue", "%")]
    [InlineData("u-dan", "all", "_")]
    public async Task Search_treats_SQL_and_wildcards_as_literal_text(string persona, string scope, string term)
    {
        var response = await api.As(persona).GetAsync(
            $"/api/requests?scope={scope}&pageSize=100&q={Uri.EscapeDataString(term)}");
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var result = await response.Read<PagedResult<RequestSummaryDto>>();
        Assert.Equal(0, result.TotalCount);
        Assert.Empty(result.Items);
    }

    [Theory]
    [InlineData("u-ava", "mine")]
    [InlineData("u-ben", "queue")]
    [InlineData("u-dan", "all")]
    public async Task Public_id_search_preserves_visibility(string persona, string scope)
    {
        var client = api.As(persona);
        var visible = await (await client.GetAsync(
            $"/api/requests?scope={scope}&pageSize=100")).Read<PagedResult<RequestSummaryDto>>();
        Assert.NotEmpty(visible.Items);
        var request = visible.Items[0];
        var result = await (await client.GetAsync(
            $"/api/requests?scope={scope}&q={request.Id}")).Read<PagedResult<RequestSummaryDto>>();
        Assert.Equal(request.Id, Assert.Single(result.Items).Id);
    }

    [Fact]
    public async Task Text_search_preserves_requester_and_department_scope()
    {
        var created = await api.As("u-ava").PostJson("/api/requests", new
        {
            title = "SearchScopeSentinel equipment",
            description = "Synthetic literal search regression record.",
            category = "equipment",
            departmentId = "IT",
            priority = "Normal",
        });
        Assert.Equal(HttpStatusCode.Created, created.StatusCode);

        foreach (var persona in new[] { "u-ava", "u-ben", "u-dan" })
        {
            var response = await api.As(persona).GetAsync("/api/requests?q=SearchScopeSentinel");
            Assert.Equal(HttpStatusCode.OK, response.StatusCode);
            Assert.Single((await response.Read<PagedResult<RequestSummaryDto>>()).Items);
        }
        foreach (var persona in new[] { "u-eli", "u-grace" })
        {
            var response = await api.As(persona).GetAsync("/api/requests?q=SearchScopeSentinel");
            Assert.Equal(HttpStatusCode.OK, response.StatusCode);
            Assert.Empty((await response.Read<PagedResult<RequestSummaryDto>>()).Items);
        }
    }
}
