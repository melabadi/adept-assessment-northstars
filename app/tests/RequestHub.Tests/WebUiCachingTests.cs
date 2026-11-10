using System.Net;

namespace RequestHub.Tests;

/// <summary>Serves a stand-in build of the web UI: an index.html and one hashed script, as `npm run build` writes them.</summary>
public sealed class WebUiFixture : ApiFixture
{
    private readonly string webRoot = Path.Combine(Path.GetTempPath(), $"rh-webroot-{Guid.NewGuid():N}");

    public WebUiFixture()
    {
        Directory.CreateDirectory(Path.Combine(webRoot, "assets"));
        File.WriteAllText(Path.Combine(webRoot, "index.html"), "<!doctype html><title>RequestHub</title><script src=\"/assets/index-1a2b3c4d.js\"></script>");
        File.WriteAllText(Path.Combine(webRoot, "assets", "index-1a2b3c4d.js"), "document.title = 'RequestHub';");
    }

    protected override IReadOnlyDictionary<string, string> Settings => new Dictionary<string, string> { ["webroot"] = webRoot };
}

/// <summary>
/// index.html names the current build's hashed scripts. A browser that keeps an old copy after a deploy asks the new
/// revision for scripts it no longer serves, so the page must be revalidated every time; the scripts themselves may be cached.
/// </summary>
public sealed class WebUiCachingTests(WebUiFixture api) : IClassFixture<WebUiFixture>
{
    [Theory]
    [InlineData("/")]
    [InlineData("/index.html")]
    [InlineData("/requests/REQ-1001")]
    public async Task The_page_is_revalidated_after_every_deploy(string path)
    {
        var response = await api.As("u-ava").GetAsync(path);

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.Equal("text/html", response.Content.Headers.ContentType?.MediaType);
        Assert.True(response.Headers.CacheControl?.NoCache, $"Cache-Control for {path}: {response.Headers.CacheControl}");
    }

    [Fact]
    public async Task Hashed_scripts_stay_cacheable()
    {
        var response = await api.As("u-ava").GetAsync("/assets/index-1a2b3c4d.js");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.False(response.Headers.CacheControl?.NoCache ?? false);
    }
}
