using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Diagnostics.HealthChecks;
using Microsoft.Extensions.Options;
using RequestHub.Core.Data;
using RequestHub.Core.Services;

namespace RequestHub.Api;

/// <summary>Tracks whether startup migration/seeding has completed; readiness stays unhealthy until it has.</summary>
public sealed class StartupState
{
    public volatile bool DatabaseReady;
    public string? LastError;
}

/// <summary>
/// Applies EF Core migrations and seeds demo data on startup (API only), retrying while the database is unreachable.
/// EF Core takes a migration lock, so several replicas starting together are safe.
/// </summary>
public sealed class DatabaseInitializer(IServiceProvider services, IConfiguration config, StartupState state, ILogger<DatabaseInitializer> logger) : BackgroundService
{
    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        var migrate = config.GetValue("Database:MigrateOnStartup", true);
        var seed = config.GetValue("Demo:SeedOnStartup", true);
        for (var attempt = 1; !stoppingToken.IsCancellationRequested; attempt++)
        {
            try
            {
                await using var scope = services.CreateAsyncScope();
                var db = scope.ServiceProvider.GetRequiredService<RequestHubDbContext>();
                if (migrate)
                {
                    await db.Database.MigrateAsync(stoppingToken);
                }

                if (seed && await scope.ServiceProvider.GetRequiredService<DemoSeeder>().SeedIfEmptyAsync(config["Demo:Industry"], stoppingToken))
                {
                    logger.LogInformation("Seeded demo data for industry {Industry}", config["Demo:Industry"] ?? "general");
                }

                state.DatabaseReady = true;
                state.LastError = null;
                logger.LogInformation("Database ready after {Attempts} attempt(s)", attempt);
                return;
            }
            catch (Exception ex) when (!stoppingToken.IsCancellationRequested)
            {
                state.LastError = ex.Message;
                var delay = TimeSpan.FromSeconds(Math.Min(30, 2 * attempt));
                logger.LogWarning(ex, "Database initialization attempt {Attempt} failed; retrying in {Delay}", attempt, delay);
                await Task.Delay(delay, stoppingToken);
            }
        }
    }
}

public sealed class StartupHealthCheck(StartupState state) : IHealthCheck
{
    public Task<HealthCheckResult> CheckHealthAsync(HealthCheckContext context, CancellationToken cancellationToken = default) =>
        Task.FromResult(state.DatabaseReady
            ? HealthCheckResult.Healthy()
            : HealthCheckResult.Unhealthy($"Database not initialized yet: {state.LastError ?? "starting"}"));
}

/// <summary>Release demo: a revision deployed with Faults:FailReadiness=true (and an expiry) never becomes ready.</summary>
public sealed class FaultReadinessCheck(IOptionsMonitor<FaultOptions> faults, TimeProvider clock) : IHealthCheck
{
    public Task<HealthCheckResult> CheckHealthAsync(HealthCheckContext context, CancellationToken cancellationToken = default)
    {
        var fault = faults.CurrentValue;
        return Task.FromResult(fault.FailReadiness && fault.IsActive(clock)
            ? HealthCheckResult.Unhealthy("Fault injection: readiness intentionally failing (Faults:FailReadiness).")
            : HealthCheckResult.Healthy());
    }
}
