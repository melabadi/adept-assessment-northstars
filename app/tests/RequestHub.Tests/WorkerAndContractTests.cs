using System.Net;
using System.Text.Json;
using System.Text.Json.Nodes;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging.Abstractions;
using Microsoft.Extensions.Options;
using RequestHub.Core.Data;
using RequestHub.Core.Domain;
using RequestHub.Core.Notifications;
using RequestHub.Core.Profiles;
using RequestHub.Core.Services;

namespace RequestHub.Tests;

public sealed class WorkerTests(ApiFixture api) : IClassFixture<ApiFixture>
{
    private sealed class FlakySender(Guid target, int failuresBeforeSuccess) : INotificationSender
    {
        public int Calls;

        public Task SendAsync(Notification notification, CancellationToken cancellationToken)
        {
            if (notification.Id != target) return Task.CompletedTask;
            Calls++;
            return Calls <= failuresBeforeSuccess ? throw new InvalidOperationException("SMTP relay unavailable") : Task.CompletedTask;
        }
    }

    private NotificationProcessor Processor(RequestHubDbContext db, INotificationSender sender, int maxAttempts) => new(
        db, sender, TimeProvider.System,
        Options.Create(new WorkerOptions { BatchSize = 1, MaxAttempts = maxAttempts, BaseBackoffSeconds = 0 }),
        new StaticOptionsMonitor<FaultOptions>(new FaultOptions()),
        NullLogger<NotificationProcessor>.Instance);

    private async Task<Guid> PendingNotificationAsync(RequestHubDbContext db)
    {
        var n = new Notification
        {
            Id = Guid.NewGuid(), Recipient = "u-ava", Type = "test.retry", CreatedAt = DateTimeOffset.UtcNow.AddYears(-1),
            NextAttemptAt = DateTimeOffset.UtcNow.AddYears(-1),
        };
        db.Notifications.Add(n);
        await db.SaveChangesAsync();
        return n.Id;
    }

    [Fact]
    public async Task Failed_delivery_is_retried_then_succeeds_exactly_once()
    {
        await using var scope = api.Factory.Services.CreateAsyncScope();
        var db = scope.ServiceProvider.GetRequiredService<RequestHubDbContext>();
        var id = await PendingNotificationAsync(db);
        var sender = new FlakySender(id, failuresBeforeSuccess: 2);
        var processor = Processor(db, sender, maxAttempts: 5);

        for (var i = 0; i < 4; i++) await processor.ProcessBatchAsync(CancellationToken.None);

        db.ChangeTracker.Clear();
        var n = await db.Notifications.SingleAsync(x => x.Id == id);
        Assert.Equal(NotificationStatus.Sent, n.Status);
        Assert.Equal(3, n.Attempts);
        Assert.Null(n.LastError);
        // A sent notification is never delivered again.
        Assert.Equal(3, sender.Calls);
    }

    [Fact]
    public async Task Delivery_gives_up_after_max_attempts()
    {
        await using var scope = api.Factory.Services.CreateAsyncScope();
        var db = scope.ServiceProvider.GetRequiredService<RequestHubDbContext>();
        var id = await PendingNotificationAsync(db);
        var processor = Processor(db, new FlakySender(id, failuresBeforeSuccess: 100), maxAttempts: 3);

        for (var i = 0; i < 5; i++) await processor.ProcessBatchAsync(CancellationToken.None);

        db.ChangeTracker.Clear();
        var n = await db.Notifications.SingleAsync(x => x.Id == id);
        Assert.Equal(NotificationStatus.Failed, n.Status);
        Assert.Equal(3, n.Attempts);
        Assert.Contains("SMTP", n.LastError);
    }

    [Fact]
    public async Task Creating_a_request_queues_notifications_for_department_reviewers()
    {
        var created = await api.As("u-ava").PostJson("/api/requests", new
        {
            title = "Projector cable for room 4",
            description = "HDMI cable missing from room 4 lectern.",
            category = "facilities",
            departmentId = "FAC",
        });
        var id = (await created.Read<RequestDetailDto>()).Id;

        await using var scope = api.Factory.Services.CreateAsyncScope();
        var db = scope.ServiceProvider.GetRequiredService<RequestHubDbContext>();
        var recipients = (await db.Notifications.Where(n => n.Type == "request.submitted").ToListAsync())
            .Where(n => n.Payload.Contains(id)).Select(n => n.Recipient).ToList();
        Assert.Contains("u-ben", recipients);
    }

    private sealed class StaticOptionsMonitor<T>(T value) : IOptionsMonitor<T>
    {
        public T CurrentValue => value;
        public T Get(string? name) => value;
        public IDisposable? OnChange(Action<T, string?> listener) => null;
    }
}

public sealed class ProfileTests
{
    [Theory]
    [InlineData("general")]
    [InlineData("manufacturing")]
    [InlineData("retail")]
    [InlineData("services")]
    [InlineData("healthcare-admin")]
    [InlineData("public-admin")]
    public void Every_profile_keeps_the_same_department_ids_and_policies(string id)
    {
        var profile = ProfileCatalog.Load(id);
        Assert.Equal(["IT", "FAC", "FIN", "HR", "OPS"], profile.Departments.Select(d => d.Id).ToArray());
        Assert.Contains(profile.Policies, p => p.Id == "POL-GOV-001");
        Assert.All(profile.Requests, r => Assert.Contains(profile.Categories, c => c.Id == r.Category));
        Assert.All(profile.Requests, r => Assert.Contains(profile.Departments, d => d.Id == r.Department));
        Assert.True(profile.Requests.Count >= 8);
    }
}

public sealed class ContractTests(ApiFixture api) : IClassFixture<ApiFixture>
{
    private static string ContractPath([System.Runtime.CompilerServices.CallerFilePath] string here = "") =>
        Path.GetFullPath(Path.Combine(Path.GetDirectoryName(here)!, "..", "..", "contracts", "openapi.json"));

    /// <summary>
    /// The committed contract must match the running API. To accept an intentional, reviewed change run:
    /// UPDATE_CONTRACT=1 dotnet test --filter OpenApi_document_matches_committed_contract
    /// </summary>
    [Fact]
    public async Task OpenApi_document_matches_committed_contract()
    {
        var response = await api.Factory.CreateClient().GetAsync("/openapi/v1.json");
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var live = Normalize(await response.Content.ReadAsStringAsync());

        if (Environment.GetEnvironmentVariable("UPDATE_CONTRACT") == "1")
        {
            await File.WriteAllTextAsync(ContractPath(), live);
        }

        Assert.True(File.Exists(ContractPath()), $"Missing {ContractPath()}. Run with UPDATE_CONTRACT=1 to create it.");
        var committed = Normalize(await File.ReadAllTextAsync(ContractPath()));
        Assert.True(committed == live, "contracts/openapi.json is out of date with the API. Review the change, bump the contract if it is breaking, then regenerate with UPDATE_CONTRACT=1.");
    }

    private static string Normalize(string json)
    {
        var node = JsonNode.Parse(json)!.AsObject();
        node.Remove("servers");
        return node.ToJsonString(new JsonSerializerOptions { WriteIndented = true }).ReplaceLineEndings("\n") + "\n";
    }
}
