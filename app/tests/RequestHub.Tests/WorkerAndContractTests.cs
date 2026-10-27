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

    private sealed class TimeoutSender(Guid[] batch, CancellationTokenSource? processorCancellation = null) : INotificationSender
    {
        public List<Guid> Calls { get; } = [];

        public Task SendAsync(Notification notification, CancellationToken cancellationToken)
        {
            if (!batch.Contains(notification.Id)) return Task.CompletedTask;
            Calls.Add(notification.Id);
            if (notification.Id != batch[1]) return Task.CompletedTask;
            processorCancellation?.Cancel();
            throw new TaskCanceledException("Sender timed out", null,
                processorCancellation is null ? new CancellationToken(canceled: true) : cancellationToken);
        }
    }

    private NotificationProcessor Processor(RequestHubDbContext db, INotificationSender sender, int maxAttempts,
        int batchSize = 1, int baseBackoffSeconds = 0) => new(
        db, sender, TimeProvider.System,
        Options.Create(new WorkerOptions { BatchSize = batchSize, MaxAttempts = maxAttempts, BaseBackoffSeconds = baseBackoffSeconds }),
        new StaticOptionsMonitor<FaultOptions>(new FaultOptions()),
        NullLogger<NotificationProcessor>.Instance);

    private async Task<Guid> PendingNotificationAsync(RequestHubDbContext db, DateTimeOffset? createdAt = null)
    {
        var n = new Notification
        {
            Id = Guid.NewGuid(), Recipient = "u-ava", Type = "test.retry", CreatedAt = createdAt ?? DateTimeOffset.UtcNow.AddYears(-1),
            NextAttemptAt = DateTimeOffset.UtcNow.AddYears(-1),
        };
        db.Notifications.Add(n);
        await db.SaveChangesAsync();
        return n.Id;
    }

    private async Task<Guid[]> PendingBatchAsync(RequestHubDbContext db)
    {
        var start = (await db.Notifications.MinAsync(n => (DateTimeOffset?)n.CreatedAt) ?? DateTimeOffset.UtcNow).AddDays(-1);
        return [
            await PendingNotificationAsync(db, start),
            await PendingNotificationAsync(db, start.AddSeconds(1)),
            await PendingNotificationAsync(db, start.AddSeconds(2)),
        ];
    }

    [Fact]
    public async Task Sender_timeout_persists_batch_and_retries_until_failed_without_resending_successes()
    {
        Guid[] ids;
        await using (var scope = api.Factory.Services.CreateAsyncScope())
        {
            ids = await PendingBatchAsync(scope.ServiceProvider.GetRequiredService<RequestHubDbContext>());
        }
        var sender = new TimeoutSender(ids);

        for (var attempt = 1; attempt <= 3; attempt++)
        {
            var before = DateTimeOffset.UtcNow;
            await using (var scope = api.Factory.Services.CreateAsyncScope())
            {
                var db = scope.ServiceProvider.GetRequiredService<RequestHubDbContext>();
                var processor = Processor(db, sender, maxAttempts: 3, batchSize: 3, baseBackoffSeconds: 60);
                try
                {
                    await processor.ProcessBatchAsync(CancellationToken.None);
                }
                catch
                {
                    await using var cleanupScope = api.Factory.Services.CreateAsyncScope();
                    var cleanupDb = cleanupScope.ServiceProvider.GetRequiredService<RequestHubDbContext>();
                    await cleanupDb.Notifications.Where(n => ids.Contains(n.Id)).ExecuteDeleteAsync();
                    throw;
                }
            }

            await using var verificationScope = api.Factory.Services.CreateAsyncScope();
            var persisted = verificationScope.ServiceProvider.GetRequiredService<RequestHubDbContext>();
            var notifications = await persisted.Notifications.Where(n => ids.Contains(n.Id)).ToDictionaryAsync(n => n.Id);
            foreach (var id in new[] { ids[0], ids[2] })
            {
                Assert.Equal(NotificationStatus.Sent, notifications[id].Status);
                Assert.Equal(1, notifications[id].Attempts);
                Assert.NotNull(notifications[id].ProcessedAt);
                Assert.Null(notifications[id].LastError);
                Assert.Equal(1, sender.Calls.Count(call => call == id));
            }
            var timedOut = notifications[ids[1]];
            Assert.Equal(attempt, timedOut.Attempts);
            Assert.Equal("Sender timed out", timedOut.LastError);
            Assert.Equal(attempt, sender.Calls.Count(call => call == ids[1]));
            if (attempt < 3)
            {
                Assert.Equal(NotificationStatus.Pending, timedOut.Status);
                Assert.Null(timedOut.ProcessedAt);
                Assert.True(timedOut.NextAttemptAt >= before.AddSeconds(60 * Math.Pow(2, attempt - 1)));
                timedOut.NextAttemptAt = before.AddSeconds(-1);
                await persisted.SaveChangesAsync();
            }
            else
            {
                Assert.Equal(NotificationStatus.Failed, timedOut.Status);
                Assert.NotNull(timedOut.ProcessedAt);
            }
        }

        Assert.Equal(ids, sender.Calls.Take(3).ToArray());
        var calls = sender.Calls.Count;
        await using var finalScope = api.Factory.Services.CreateAsyncScope();
        await Processor(finalScope.ServiceProvider.GetRequiredService<RequestHubDbContext>(), sender, maxAttempts: 3, batchSize: 3)
            .ProcessBatchAsync(CancellationToken.None);
        Assert.Equal(calls, sender.Calls.Count);
    }

    [Fact]
    public async Task Processor_cancellation_during_delivery_propagates_without_committing_batch()
    {
        Guid[] ids;
        await using (var scope = api.Factory.Services.CreateAsyncScope())
        {
            ids = await PendingBatchAsync(scope.ServiceProvider.GetRequiredService<RequestHubDbContext>());
        }
        using var cancellation = new CancellationTokenSource();
        var sender = new TimeoutSender(ids, cancellation);
        try
        {
            await using (var scope = api.Factory.Services.CreateAsyncScope())
            {
                var processor = Processor(scope.ServiceProvider.GetRequiredService<RequestHubDbContext>(), sender, maxAttempts: 3, batchSize: 3);
                var error = await Assert.ThrowsAsync<TaskCanceledException>(() => processor.ProcessBatchAsync(cancellation.Token));
                Assert.Equal(cancellation.Token, error.CancellationToken);
            }

            Assert.True(cancellation.IsCancellationRequested);
            Assert.Equal(ids.Take(2).ToArray(), sender.Calls.ToArray());
            await using var verificationScope = api.Factory.Services.CreateAsyncScope();
            var db = verificationScope.ServiceProvider.GetRequiredService<RequestHubDbContext>();
            var notifications = await db.Notifications.Where(n => ids.Contains(n.Id)).ToListAsync();
            Assert.Equal(3, notifications.Count);
            Assert.All(notifications, n =>
            {
                Assert.Equal(NotificationStatus.Pending, n.Status);
                Assert.Equal(0, n.Attempts);
                Assert.Null(n.LastError);
                Assert.Null(n.ProcessedAt);
            });
        }
        finally
        {
            await using var cleanupScope = api.Factory.Services.CreateAsyncScope();
            var db = cleanupScope.ServiceProvider.GetRequiredService<RequestHubDbContext>();
            await db.Notifications.Where(n => ids.Contains(n.Id)).ExecuteDeleteAsync();
        }
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
