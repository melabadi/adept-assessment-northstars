using System.Net;
using System.Net.Http.Headers;
using System.Text;
using RequestHub.Core.Services;

namespace RequestHub.Tests;

public sealed class AuthorizationTests(ApiFixture api) : IClassFixture<ApiFixture>
{
    [Fact]
    public async Task Anonymous_calls_are_rejected()
    {
        var response = await api.Factory.CreateClient().GetAsync("/api/requests");
        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
    }

    [Fact]
    public async Task Unknown_persona_is_rejected()
    {
        var response = await api.As("u-nobody").GetAsync("/api/me");
        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
    }

    [Fact]
    public async Task Approver_cannot_open_a_request_outside_their_departments()
    {
        // Grace covers FIN and HR; REQ-1001 is routed to IT.
        var response = await api.As("u-grace").GetAsync("/api/requests/REQ-1001");
        Assert.Equal(HttpStatusCode.Forbidden, response.StatusCode);
        Assert.Equal("auth.department_forbidden", await response.Code());
    }

    [Fact]
    public async Task Approver_cannot_decide_outside_their_departments()
    {
        var response = await api.As("u-grace").PostJson("/api/requests/REQ-1002/decisions", new { outcome = "Approved" });
        Assert.Equal(HttpStatusCode.Forbidden, response.StatusCode);
        Assert.Equal("auth.department_forbidden", await response.Code());
    }

    [Fact]
    public async Task Team_queue_only_contains_the_callers_departments()
    {
        var queue = await (await api.As("u-grace").GetAsync("/api/requests?scope=queue&pageSize=100")).Read<PagedResult<RequestSummaryDto>>();
        Assert.NotEmpty(queue.Items);
        Assert.All(queue.Items, r => Assert.Contains(r.DepartmentId, new[] { "FIN", "HR" }));
    }

    [Fact]
    public async Task Requester_only_sees_their_own_requests()
    {
        var queue = await (await api.As("u-eli").GetAsync("/api/requests?scope=queue&pageSize=100")).Read<PagedResult<RequestSummaryDto>>();
        Assert.NotEmpty(queue.Items);
        Assert.All(queue.Items, r => Assert.Equal("u-eli", r.Requester.Id));
    }

    [Fact]
    public async Task Requester_cannot_read_someone_elses_request()
    {
        var response = await api.As("u-eli").GetAsync("/api/requests/REQ-1001");
        Assert.Equal(HttpStatusCode.Forbidden, response.StatusCode);
    }

    [Fact]
    public async Task Demo_reset_requires_admin()
    {
        var response = await api.As("u-ben").PostAsync("/api/admin/reset", null);
        Assert.Equal(HttpStatusCode.Forbidden, response.StatusCode);
    }

    [Fact]
    public async Task State_changing_cookie_request_without_client_header_is_rejected()
    {
        var client = api.Factory.CreateClient();
        using var message = new HttpRequestMessage(HttpMethod.Post, "/api/requests")
        {
            Content = new StringContent("{}", Encoding.UTF8, "application/json"),
        };
        message.Headers.Add("Cookie", "rh_user=u-ava");
        var response = await client.SendAsync(message);
        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
    }

    [Fact]
    public async Task Meta_exposes_contract_without_configuration_secrets()
    {
        var response = await api.Factory.CreateClient().GetAsync("/api/meta");
        var body = await response.Content.ReadAsStringAsync();
        Assert.Contains("requesthub.v1", body);
        Assert.DoesNotContain("Password", body, StringComparison.OrdinalIgnoreCase);
        Assert.DoesNotContain("Host=", body, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public async Task Health_endpoints_are_anonymous()
    {
        var client = api.Factory.CreateClient();
        Assert.Equal(HttpStatusCode.OK, (await client.GetAsync("/health/live")).StatusCode);
        Assert.Equal(HttpStatusCode.OK, (await client.GetAsync("/health/ready")).StatusCode);
    }

    [Fact]
    public async Task Attachments_are_only_downloadable_by_people_who_can_see_the_request()
    {
        var ava = api.As("u-ava");
        using var form = new MultipartFormDataContent();
        var file = new ByteArrayContent(Encoding.UTF8.GetBytes("asset,TAG-4471\nbattery,failed\n"));
        file.Headers.ContentType = new MediaTypeHeaderValue("text/csv");
        form.Add(file, "file", "battery-report.csv");
        var upload = await ava.PostAsync("/api/requests/REQ-1001/attachments", form);
        Assert.Equal(HttpStatusCode.Created, upload.StatusCode);
        var attachment = await upload.Read<AttachmentDto>();

        var owner = await ava.GetAsync(attachment.DownloadUrl);
        Assert.Equal(HttpStatusCode.OK, owner.StatusCode);
        Assert.Contains("TAG-4471", await owner.Content.ReadAsStringAsync());
        Assert.Equal("attachment", owner.Content.Headers.ContentDisposition?.DispositionType);

        var outsider = await api.As("u-grace").GetAsync(attachment.DownloadUrl);
        Assert.Equal(HttpStatusCode.Forbidden, outsider.StatusCode);
    }

    [Theory]
    [InlineData("tool.exe", "MZ binary")]
    [InlineData("fake.pdf", "not really a pdf")]
    public async Task Disallowed_or_disguised_attachments_are_rejected(string name, string content)
    {
        using var form = new MultipartFormDataContent();
        form.Add(new ByteArrayContent(Encoding.UTF8.GetBytes(content)), "file", name);
        var response = await api.As("u-ava").PostAsync("/api/requests/REQ-1001/attachments", form);
        Assert.Equal(HttpStatusCode.UnsupportedMediaType, response.StatusCode);
    }

    [Fact]
    public async Task Oversized_attachments_are_rejected()
    {
        using var form = new MultipartFormDataContent();
        form.Add(new ByteArrayContent(new byte[6 * 1024 * 1024]), "file", "big.txt");
        var response = await api.As("u-ava").PostAsync("/api/requests/REQ-1001/attachments", form);
        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
    }
}
