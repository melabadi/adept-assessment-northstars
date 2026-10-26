using Azure.Core;
using Azure.Identity;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.DependencyInjection.Extensions;
using Npgsql;
using RequestHub.Core.Data;
using RequestHub.Core.Notifications;
using RequestHub.Core.Profiles;
using RequestHub.Core.Triage;

namespace RequestHub.Core.Services;

public static class CoreServiceExtensions
{
    private const string PostgresEntraScope = "https://ossrdbms-aad.database.windows.net/.default";

    /// <summary>
    /// Registers the database, profile, workflow, seeder, and notification processor.
    /// Set Database:UseEntraAuth=true in Azure to authenticate to PostgreSQL with the app's managed identity (no password).
    /// </summary>
    public static IServiceCollection AddRequestHubCore(this IServiceCollection services, IConfiguration config)
    {
        services.TryAddSingleton(TimeProvider.System);
        services.Configure<TriageOptions>(config.GetSection(TriageOptions.Section));
        services.Configure<WorkerOptions>(config.GetSection(WorkerOptions.Section));
        services.Configure<FaultOptions>(config.GetSection(FaultOptions.Section));
        services.AddSingleton(_ => ProfileCatalog.Load(config["Demo:Industry"]));

        var connectionString = config.GetConnectionString("RequestHub")
            ?? throw new InvalidOperationException("ConnectionStrings:RequestHub is not configured.");
        var builder = new NpgsqlDataSourceBuilder(connectionString);
        if (config.GetValue<bool>("Database:UseEntraAuth"))
        {
            var credential = new DefaultAzureCredential(new DefaultAzureCredentialOptions
            {
                ManagedIdentityClientId = config["AZURE_CLIENT_ID"],
            });
            builder.UsePeriodicPasswordProvider(
                async (_, ct) => (await credential.GetTokenAsync(new TokenRequestContext([PostgresEntraScope]), ct)).Token,
                TimeSpan.FromMinutes(50),
                TimeSpan.FromSeconds(5));
        }

        var dataSource = builder.Build();
        services.AddSingleton(dataSource);
        services.AddDbContext<RequestHubDbContext>(o => o.UseNpgsql(dataSource));

        services.TryAddSingleton<ITriageProvider, SampleRulesTriageProvider>();
        services.TryAddSingleton<INotificationSender, LogNotificationSender>();
        services.AddScoped<RequestWorkflow>();
        services.AddScoped<DemoSeeder>();
        services.AddScoped<NotificationProcessor>();
        return services;
    }
}
