using System.Net;
using System.Net.Http.Json;
using System.Text.Json;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.AspNetCore.TestHost;
using Microsoft.Extensions.DependencyInjection;
using Npgsql;

namespace RequestHub.Tests;

/// <summary>
/// Boots the real API against a fresh PostgreSQL database per test class.
/// Set REQUESTHUB_TEST_PG to a server connection string (no database); defaults to the local dev container.
/// </summary>
public class ApiFixture : IAsyncLifetime
{
    public static readonly JsonSerializerOptions Json = new(JsonSerializerDefaults.Web);

    private readonly string database = $"rh_test_{Guid.NewGuid():N}"[..20];
    private readonly string storagePath = Path.Combine(Path.GetTempPath(), $"rh-attachments-{Guid.NewGuid():N}");
    private WebApplicationFactory<Program>? factory;

    public static string ServerConnectionString =>
        Environment.GetEnvironmentVariable("REQUESTHUB_TEST_PG") ?? "Host=localhost;Port=5432;Username=requesthub;Password=devpass";

    public string ConnectionString => $"{ServerConnectionString};Database={database}";

    public WebApplicationFactory<Program> Factory => factory ?? throw new InvalidOperationException("Fixture not initialized.");

    /// <summary>Override to replace services (for example a fake triage provider).</summary>
    protected virtual void ConfigureTestServices(IServiceCollection services)
    {
    }

    /// <summary>Extra configuration settings for a derived fixture.</summary>
    protected virtual IReadOnlyDictionary<string, string> Settings { get; } = new Dictionary<string, string>();

    public async ValueTask InitializeAsync()
    {
        await using (var conn = new NpgsqlConnection($"{ServerConnectionString};Database=postgres"))
        {
            await conn.OpenAsync();
            await using var cmd = new NpgsqlCommand($"CREATE DATABASE \"{database}\"", conn);
            await cmd.ExecuteNonQueryAsync();
        }

        factory = new WebApplicationFactory<Program>().WithWebHostBuilder(b =>
        {
            b.UseEnvironment("Testing");
            b.UseSetting("ConnectionStrings:RequestHub", ConnectionString);
            b.UseSetting("Storage:LocalPath", storagePath);
            b.UseSetting("Auth:Mode", "Development");
            b.UseSetting("Demo:AllowReset", "true");
            foreach (var (key, value) in Settings)
            {
                b.UseSetting(key, value);
            }

            b.ConfigureTestServices(ConfigureTestServices);
        });

        using var client = factory.CreateClient();
        var deadline = DateTime.UtcNow.AddSeconds(60);
        while (true)
        {
            var ready = await client.GetAsync("/health/ready");
            if (ready.StatusCode == HttpStatusCode.OK) break;
            if (DateTime.UtcNow > deadline) throw new TimeoutException($"API never became ready: {await ready.Content.ReadAsStringAsync()}");
            await Task.Delay(250);
        }
    }

    public HttpClient As(string persona)
    {
        var client = Factory.CreateClient();
        client.DefaultRequestHeaders.Add("X-RequestHub-User", persona);
        return client;
    }

    public async ValueTask DisposeAsync()
    {
        factory?.Dispose();
        NpgsqlConnection.ClearAllPools();
        await using var conn = new NpgsqlConnection($"{ServerConnectionString};Database=postgres");
        await conn.OpenAsync();
        await using var cmd = new NpgsqlCommand($"DROP DATABASE IF EXISTS \"{database}\" WITH (FORCE)", conn);
        await cmd.ExecuteNonQueryAsync();
        if (Directory.Exists(storagePath)) Directory.Delete(storagePath, recursive: true);
        GC.SuppressFinalize(this);
    }
}

public static class HttpExtensions
{
    public static async Task<T> Read<T>(this HttpResponseMessage response) =>
        (await response.Content.ReadFromJsonAsync<T>(ApiFixture.Json))!;

    public static async Task<string> Code(this HttpResponseMessage response)
    {
        var doc = await response.Content.ReadFromJsonAsync<JsonElement>(ApiFixture.Json);
        return doc.TryGetProperty("code", out var code) ? code.GetString() ?? "" : "";
    }

    public static async Task<HttpResponseMessage> PostJson(this HttpClient client, string url, object body, string? idempotencyKey = null)
    {
        using var message = new HttpRequestMessage(HttpMethod.Post, url) { Content = JsonContent.Create(body) };
        if (idempotencyKey is not null) message.Headers.Add("Idempotency-Key", idempotencyKey);
        return await client.SendAsync(message);
    }
}
