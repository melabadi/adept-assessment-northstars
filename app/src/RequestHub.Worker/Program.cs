using System.Diagnostics.Metrics;
using Azure.Monitor.OpenTelemetry.AspNetCore;
using Microsoft.AspNetCore.Diagnostics.HealthChecks;
using Microsoft.Extensions.Options;
using Npgsql;
using OpenTelemetry.Metrics;
using OpenTelemetry.Trace;
using RequestHub.Core.Data;
using RequestHub.Core.Notifications;
using RequestHub.Core.Services;

var builder = WebApplication.CreateBuilder(args);

builder.Services.AddRequestHubCore(builder.Configuration);
builder.Services.AddSingleton<BacklogMetrics>();
builder.Services.AddHostedService<NotificationWorker>();
builder.Services.AddHealthChecks().AddDbContextCheck<RequestHubDbContext>("database", tags: ["ready"]);

if (!string.IsNullOrEmpty(builder.Configuration["APPLICATIONINSIGHTS_CONNECTION_STRING"]))
{
    builder.Services.AddOpenTelemetry()
        .UseAzureMonitor()
        .WithTracing(t => t.AddSource(RequestHubTelemetry.SourceName).AddNpgsql())
        .WithMetrics(m => m.AddMeter(RequestHubTelemetry.SourceName));
}

var app = builder.Build();
app.MapHealthChecks("/health/live", new HealthCheckOptions { Predicate = _ => false });
app.MapHealthChecks("/health/ready", new HealthCheckOptions { Predicate = c => c.Tags.Contains("ready") });
app.MapGet("/", (BacklogMetrics metrics) => Results.Ok(new { service = "requesthub-worker", backlog = metrics.Latest }));
app.Run();

/// <summary>Publishes backlog gauges (pending count and oldest pending age) used by the Operate demo alert.</summary>
public sealed class BacklogMetrics
{
    public BacklogMetrics()
    {
        RequestHubTelemetry.Meter.CreateObservableGauge("requesthub.notifications.pending", () => Latest.Pending);
        RequestHubTelemetry.Meter.CreateObservableGauge("requesthub.notifications.oldest_pending_age_seconds", () => Latest.OldestPendingAgeSeconds, unit: "s");
        RequestHubTelemetry.Meter.CreateObservableGauge("requesthub.notifications.failed", () => Latest.Failed);
    }

    public BacklogSnapshot Latest { get; set; } = new(0, 0, 0);
}

/// <summary>Polls for pending notifications and delivers them. Several replicas can run safely (SKIP LOCKED).</summary>
public sealed class NotificationWorker(
    IServiceProvider services,
    BacklogMetrics metrics,
    IOptions<WorkerOptions> options,
    IOptionsMonitor<FaultOptions> faults,
    TimeProvider clock,
    ILogger<NotificationWorker> logger) : BackgroundService
{
    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        var lastReport = DateTimeOffset.MinValue;
        while (!stoppingToken.IsCancellationRequested)
        {
            try
            {
                await using var scope = services.CreateAsyncScope();
                var processor = scope.ServiceProvider.GetRequiredService<NotificationProcessor>();
                var processed = await processor.ProcessBatchAsync(stoppingToken);
                metrics.Latest = await processor.GetBacklogAsync(stoppingToken);

                if (clock.GetUtcNow() - lastReport > TimeSpan.FromSeconds(30))
                {
                    lastReport = clock.GetUtcNow();
                    var fault = faults.CurrentValue;
                    logger.LogInformation(
                        "Notification backlog: pending={Pending} oldestPendingAgeSeconds={OldestAge} failed={Failed} workerDelayFaultActive={FaultActive}",
                        metrics.Latest.Pending, metrics.Latest.OldestPendingAgeSeconds, metrics.Latest.Failed, fault.IsActive(clock) && fault.WorkerDelayMs > 0);
                }

                if (processed == 0)
                {
                    await Task.Delay(options.Value.PollIntervalMs, stoppingToken);
                }
            }
            catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested)
            {
                return;
            }
            catch (Exception ex)
            {
                // The API owns migrations; the worker waits until the schema exists.
                logger.LogWarning(ex, "Notification worker iteration failed; retrying in 5 seconds");
                await Task.Delay(TimeSpan.FromSeconds(5), stoppingToken);
            }
        }
    }
}
