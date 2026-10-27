using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;
using RequestHub.Core.Data;
using RequestHub.Core.Domain;
using RequestHub.Core.Services;

namespace RequestHub.Core.Notifications;

public sealed class WorkerOptions
{
    public const string Section = "Worker";
    public int BatchSize { get; set; } = 20;
    public int PollIntervalMs { get; set; } = 1000;
    public int MaxAttempts { get; set; } = 5;
    public int BaseBackoffSeconds { get; set; } = 2;
}

/// <summary>Delivers a notification. The baseline only records delivery; no external email or Teams message is sent.</summary>
public interface INotificationSender
{
    Task SendAsync(Notification notification, CancellationToken cancellationToken);
}

public sealed class LogNotificationSender(ILogger<LogNotificationSender> logger) : INotificationSender
{
    public Task SendAsync(Notification notification, CancellationToken cancellationToken)
    {
        logger.LogInformation("Delivered notification {NotificationId} ({Type}) to {Recipient}", notification.Id, notification.Type, notification.Recipient);
        return Task.CompletedTask;
    }
}

public sealed record BacklogSnapshot(int Pending, double OldestPendingAgeSeconds, int Failed);

/// <summary>
/// Claims pending notifications with FOR UPDATE SKIP LOCKED so several workers never process the same row.
/// Delivery is at-least-once; a notification id is stable so receivers can de-duplicate.
/// Failures retry with exponential backoff up to MaxAttempts, then the notification is marked Failed.
/// </summary>
public sealed class NotificationProcessor(
    RequestHubDbContext db,
    INotificationSender sender,
    TimeProvider clock,
    IOptions<WorkerOptions> options,
    IOptionsMonitor<FaultOptions> faults,
    ILogger<NotificationProcessor> logger)
{
    public async Task<int> ProcessBatchAsync(CancellationToken ct)
    {
        var settings = options.Value;
        var now = clock.GetUtcNow();
        await using var tx = await db.Database.BeginTransactionAsync(ct);
        var batch = await db.Notifications
            .FromSqlInterpolated($"""
                SELECT * FROM "Notifications"
                WHERE "Status" = 'Pending' AND "NextAttemptAt" <= {now}
                ORDER BY "CreatedAt"
                LIMIT {settings.BatchSize}
                FOR UPDATE SKIP LOCKED
                """)
            .ToListAsync(ct);

        var fault = faults.CurrentValue;
        var delay = fault.IsActive(clock) && fault.WorkerDelayMs > 0 ? fault.WorkerDelayMs : 0;
        foreach (var notification in batch)
        {
            using var activity = RequestHubTelemetry.ActivitySource.StartActivity("notification.deliver");
            activity?.SetTag("requesthub.notification.type", notification.Type);
            if (delay > 0)
            {
                activity?.SetTag("requesthub.fault.worker_delay_ms", delay);
                await Task.Delay(delay, ct);
            }

            notification.Attempts++;
            try
            {
                await sender.SendAsync(notification, ct);
                notification.Status = NotificationStatus.Sent;
                notification.ProcessedAt = clock.GetUtcNow();
                notification.LastError = null;
                RequestHubTelemetry.NotificationsProcessed.Add(1, new KeyValuePair<string, object?>("outcome", "sent"));
            }
            catch (Exception ex) when (ex is not OperationCanceledException || !ct.IsCancellationRequested)
            {
                notification.LastError = ex.Message.Length > 900 ? ex.Message[..900] : ex.Message;
                if (notification.Attempts >= settings.MaxAttempts)
                {
                    notification.Status = NotificationStatus.Failed;
                    notification.ProcessedAt = clock.GetUtcNow();
                    RequestHubTelemetry.NotificationsProcessed.Add(1, new KeyValuePair<string, object?>("outcome", "failed"));
                    logger.LogError(ex, "Notification {NotificationId} failed permanently after {Attempts} attempts", notification.Id, notification.Attempts);
                }
                else
                {
                    var backoff = TimeSpan.FromSeconds(settings.BaseBackoffSeconds * Math.Pow(2, notification.Attempts - 1));
                    notification.NextAttemptAt = clock.GetUtcNow().Add(backoff);
                    RequestHubTelemetry.NotificationsProcessed.Add(1, new KeyValuePair<string, object?>("outcome", "retry"));
                    logger.LogWarning("Notification {NotificationId} attempt {Attempts} failed; retrying in {Backoff}", notification.Id, notification.Attempts, backoff);
                }
            }
        }

        await db.SaveChangesAsync(ct);
        await tx.CommitAsync(ct);
        return batch.Count;
    }

    public async Task<BacklogSnapshot> GetBacklogAsync(CancellationToken ct)
    {
        var pending = db.Notifications.AsNoTracking().Where(n => n.Status == NotificationStatus.Pending);
        var count = await pending.CountAsync(ct);
        var oldest = count == 0 ? (DateTimeOffset?)null : await pending.MinAsync(n => (DateTimeOffset?)n.CreatedAt, ct);
        var failed = await db.Notifications.AsNoTracking().CountAsync(n => n.Status == NotificationStatus.Failed, ct);
        var age = oldest is null ? 0 : Math.Max(0, (clock.GetUtcNow() - oldest.Value).TotalSeconds);
        return new BacklogSnapshot(count, Math.Round(age, 1), failed);
    }
}
