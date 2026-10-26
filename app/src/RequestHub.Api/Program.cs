using Azure.Monitor.OpenTelemetry.AspNetCore;
using Microsoft.AspNetCore.Diagnostics.HealthChecks;
using Microsoft.AspNetCore.Http.Json;
using Microsoft.OpenApi;
using Npgsql;
using OpenTelemetry.Metrics;
using OpenTelemetry.Trace;
using RequestHub.Api;
using RequestHub.Api.Auth;
using RequestHub.Api.Endpoints;
using RequestHub.Api.Storage;
using RequestHub.Core.Data;
using RequestHub.Core.Services;

var builder = WebApplication.CreateBuilder(args);

builder.Services.AddRequestHubCore(builder.Configuration);
builder.AddRequestHubAuth();
builder.Services.AddProblemDetails();
// Malformed request bodies return 400 (not 500) in every environment.
builder.Services.Configure<RouteHandlerOptions>(o => o.ThrowOnBadRequest = false);
builder.Services.Configure<JsonOptions>(o => o.SerializerOptions.PropertyNamingPolicy = System.Text.Json.JsonNamingPolicy.CamelCase);
builder.Services.AddOpenApi(o => o.AddDocumentTransformer((doc, _, _) =>
{
    doc.Servers?.Clear();
    doc.Info = new OpenApiInfo
    {
        Title = "RequestHub API",
        Version = ApiEndpoints.ContractVersion,
        Description = "Request-and-approval API shared by every AI-SDLC demo phase. See app/contracts/README.md for errors, idempotency, concurrency, pagination, and authorization rules.",
    };
    return Task.CompletedTask;
}));

var storage = builder.Configuration.GetSection(StorageSettings.Section).Get<StorageSettings>() ?? new StorageSettings();
builder.Services.AddSingleton(storage);
if (string.Equals(storage.Provider, "Blob", StringComparison.OrdinalIgnoreCase))
{
    builder.Services.AddSingleton<IAttachmentStore, BlobAttachmentStore>();
}
else
{
    builder.Services.AddSingleton<IAttachmentStore, LocalAttachmentStore>();
}

builder.Services.AddSingleton<StartupState>();
builder.Services.AddHostedService<DatabaseInitializer>();
builder.Services.AddHealthChecks()
    .AddCheck<StartupHealthCheck>("startup", tags: ["ready"])
    .AddDbContextCheck<RequestHubDbContext>("database", tags: ["ready"])
    .AddCheck<FaultReadinessCheck>("fault-injection", tags: ["ready"]);

if (!string.IsNullOrEmpty(builder.Configuration["APPLICATIONINSIGHTS_CONNECTION_STRING"]))
{
    builder.Services.AddOpenTelemetry()
        .UseAzureMonitor()
        .WithTracing(t => t.AddSource(RequestHubTelemetry.SourceName).AddNpgsql())
        .WithMetrics(m => m.AddMeter(RequestHubTelemetry.SourceName));
}

var app = builder.Build();

app.UseExceptionHandler();
app.UseStatusCodePages();
app.Use(async (ctx, next) =>
{
    ctx.Response.Headers.XContentTypeOptions = "nosniff";
    ctx.Response.Headers["Referrer-Policy"] = "no-referrer";
    ctx.Response.Headers.XFrameOptions = "DENY";
    if (System.Diagnostics.Activity.Current is { } activity)
    {
        ctx.Response.Headers["X-Correlation-Id"] = activity.TraceId.ToString();
    }

    await next();
});

app.MapHealthChecks("/health/live", new HealthCheckOptions { Predicate = _ => false });
app.MapHealthChecks("/health/ready", new HealthCheckOptions { Predicate = c => c.Tags.Contains("ready") });

app.UseDefaultFiles();
app.UseStaticFiles();
app.UseAuthentication();
app.UseAuthorization();
app.UseCustomHeaderCsrfGuard();

app.MapOpenApi("/openapi/{documentName}.json");
app.MapRequestHubApi();
app.MapFallback("/api/{**path}", () => Results.Problem(statusCode: 404, title: "route.not_found", detail: "No such API route."));
app.MapFallbackToFile("index.html");

app.Run();

public partial class Program;
