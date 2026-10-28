using System.Net;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Diagnostics;
using Microsoft.Extensions.DependencyInjection;
using RequestHub.Core.Data;
using RequestHub.Core.Domain;
using RequestHub.Core.Services;

namespace RequestHub.Tests;

public sealed class DecisionRecoveryAuthorizationTests(DecisionRecoveryFixture api) : IClassFixture<DecisionRecoveryFixture>
{
    [Fact]
    public async Task Decision_recovery_does_not_expose_decision_after_request_moves_to_inaccessible_department()
    {
        var created = await api.As("u-ava").PostJson("/api/requests", new
        {
            title = "Desk organizer for studio 4",
            description = "Storage is needed for the shared studio desk.",
            category = "equipment",
            departmentId = "IT",
            priority = "Normal",
        });
        var id = (await created.Read<RequestDetailDto>()).Id;
        api.RaceNextDecisionWithReroute();

        var response = await api.As("u-chloe").PostJson($"/api/requests/{id}/decisions", new
        {
            outcome = "Approved",
        });

        Assert.Equal(HttpStatusCode.Forbidden, response.StatusCode);
        Assert.Equal("auth.department_forbidden", await response.Code());
        Assert.DoesNotContain("Sensitive competing comment.", await response.Content.ReadAsStringAsync());
    }
}

public sealed class DecisionRecoveryFixture : ApiFixture
{
    private readonly DecisionRaceInterceptor race = new();

    protected override void ConfigureTestServices(IServiceCollection services)
    {
        race.ConnectionString = ConnectionString;
        services.AddSingleton(race);
        services.AddDbContext<RequestHubDbContext>((provider, options) =>
            options.AddInterceptors(provider.GetRequiredService<DecisionRaceInterceptor>()));
    }

    public void RaceNextDecisionWithReroute() => race.Arm();
}

public sealed class DecisionRaceInterceptor : SaveChangesInterceptor
{
    private int armed;

    public string ConnectionString { private get; set; } = "";

    public void Arm() => Interlocked.Exchange(ref armed, 1);

    public override async ValueTask<InterceptionResult<int>> SavingChangesAsync(
        DbContextEventData eventData,
        InterceptionResult<int> result,
        CancellationToken cancellationToken = default)
    {
        if (eventData.Context is not RequestHubDbContext context)
        {
            return result;
        }

        var pendingDecision = context.ChangeTracker.Entries<ApprovalDecision>()
            .FirstOrDefault(entry => entry.State == EntityState.Added)?.Entity;
        if (pendingDecision is null || Interlocked.CompareExchange(ref armed, 0, 1) != 1)
        {
            return result;
        }

        var options = new DbContextOptionsBuilder<RequestHubDbContext>()
            .UseNpgsql(ConnectionString)
            .Options;
        await using var competingDb = new RequestHubDbContext(options);
        var request = await competingDb.Requests.SingleAsync(r => r.Id == pendingDecision.RequestId, cancellationToken);
        request.DepartmentId = "FIN";
        request.Status = RequestStatus.Rejected;
        request.UpdatedAt = DateTimeOffset.UtcNow;
        competingDb.Decisions.Add(new ApprovalDecision
        {
            Id = Guid.NewGuid(),
            RequestId = request.Id,
            Outcome = DecisionOutcome.Rejected,
            DecidedById = "u-grace",
            Comment = "Sensitive competing comment.",
            DecidedAt = DateTimeOffset.UtcNow,
        });
        await competingDb.SaveChangesAsync(cancellationToken);

        return result;
    }
}
