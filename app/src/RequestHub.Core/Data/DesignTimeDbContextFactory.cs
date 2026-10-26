using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Design;

namespace RequestHub.Core.Data;

/// <summary>Used only by `dotnet ef` to create migrations; no database connection is opened.</summary>
public sealed class DesignTimeDbContextFactory : IDesignTimeDbContextFactory<RequestHubDbContext>
{
    public RequestHubDbContext CreateDbContext(string[] args) =>
        new(new DbContextOptionsBuilder<RequestHubDbContext>()
            .UseNpgsql("Host=localhost;Database=requesthub_design;Username=design;Password=design")
            .Options);
}
