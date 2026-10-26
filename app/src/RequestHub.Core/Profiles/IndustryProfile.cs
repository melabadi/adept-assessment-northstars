using System.Reflection;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace RequestHub.Core.Profiles;

/// <summary>
/// An industry profile changes terminology, seed records, and policy wording.
/// Department and category ids are stable across profiles so business logic never forks.
/// </summary>
public sealed class IndustryProfile
{
    public required string Id { get; init; }
    public string? Inherits { get; init; }
    public required LocalizedName Name { get; init; }
    public string Description { get; init; } = "";
    public List<string> Sites { get; init; } = [];
    public List<ProfileDepartment> Departments { get; init; } = [];
    public List<ProfileCategory> Categories { get; init; } = [];
    public List<RoutingPolicy> Policies { get; init; } = [];
    public List<SeedRequest> Requests { get; init; } = [];

    public RoutingPolicy? FindPolicy(string id) =>
        Policies.FirstOrDefault(p => string.Equals(p.Id, id, StringComparison.OrdinalIgnoreCase));
}

public sealed record LocalizedName(string En, string Fr);

public sealed class ProfileDepartment
{
    public required string Id { get; init; }
    public required string En { get; init; }
    public required string Fr { get; init; }
}

public sealed class ProfileCategory
{
    public required string Id { get; init; }
    public required string En { get; init; }
    public required string Fr { get; init; }
}

public sealed class RoutingPolicy
{
    public required string Id { get; init; }
    public required string Version { get; init; }
    /// <summary>routing | spend | safety | fallback | governance</summary>
    public required string Kind { get; init; }
    public required string Title { get; init; }
    public required string Text { get; init; }
    public string RouteTo { get; init; } = "";
    public string? Priority { get; init; }
    public decimal? Threshold { get; init; }
    public List<string> Categories { get; init; } = [];
    public List<string> Keywords { get; init; } = [];

    [JsonIgnore]
    public string Ref => $"{Id}@{Version}";
}

public sealed class SeedRequest
{
    public required string Title { get; init; }
    public required string Description { get; init; }
    public required string Category { get; init; }
    public required string Department { get; init; }
    public string Priority { get; init; } = "Normal";
    public string? Status { get; init; }
    public string? Requester { get; init; }
    public int? AgeHours { get; init; }
    public List<SeedComment> Comments { get; init; } = [];
    public SeedDecision? Decision { get; init; }
    public SeedRecommendation? Recommendation { get; init; }
}

public sealed record SeedComment(string Author, string Body);

public sealed record SeedDecision(string Outcome, string By, string? Comment);

public sealed record SeedRecommendation(string Department, string Priority, List<string> Policies, string Rationale);

public static class ProfileCatalog
{
    public const string DefaultProfile = "general";

    public static readonly string[] Available =
        ["general", "manufacturing", "retail", "services", "healthcare-admin", "public-admin"];

    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNameCaseInsensitive = true,
        ReadCommentHandling = JsonCommentHandling.Skip,
    };

    private static readonly Dictionary<string, IndustryProfile> Cache = new(StringComparer.OrdinalIgnoreCase);
    private static readonly Lock CacheLock = new();

    public static IndustryProfile Load(string? id)
    {
        var key = string.IsNullOrWhiteSpace(id) ? DefaultProfile : id.Trim().ToLowerInvariant();
        if (!Available.Contains(key))
        {
            throw new ArgumentException($"Unknown industry profile '{id}'. Available: {string.Join(", ", Available)}.");
        }

        lock (CacheLock)
        {
            if (Cache.TryGetValue(key, out var cached))
            {
                return cached;
            }

            var raw = ReadRaw(key);
            var resolved = raw.Inherits is null ? raw : Merge(Load(raw.Inherits), raw);
            Cache[key] = resolved;
            return resolved;
        }
    }

    private static IndustryProfile ReadRaw(string id)
    {
        var assembly = typeof(ProfileCatalog).Assembly;
        var resourceName = assembly.GetManifestResourceNames()
            .Single(n => n.EndsWith($".Profiles.{id}.json", StringComparison.OrdinalIgnoreCase));
        using var stream = assembly.GetManifestResourceStream(resourceName)
            ?? throw new InvalidOperationException($"Profile resource {resourceName} not found.");
        return JsonSerializer.Deserialize<IndustryProfile>(stream, JsonOptions)
            ?? throw new InvalidOperationException($"Profile {id} is empty.");
    }

    /// <summary>Child values override parent values by id; lists that the child omits are inherited.</summary>
    private static IndustryProfile Merge(IndustryProfile parent, IndustryProfile child) => new()
    {
        Id = child.Id,
        Inherits = child.Inherits,
        Name = child.Name,
        Description = string.IsNullOrEmpty(child.Description) ? parent.Description : child.Description,
        Sites = child.Sites.Count > 0 ? child.Sites : parent.Sites,
        Departments = MergeById(parent.Departments, child.Departments, d => d.Id),
        Categories = MergeById(parent.Categories, child.Categories, c => c.Id),
        Policies = MergeById(parent.Policies, child.Policies, p => p.Id),
        Requests = child.Requests.Count > 0 ? child.Requests : parent.Requests,
    };

    private static List<T> MergeById<T>(List<T> parent, List<T> child, Func<T, string> id)
    {
        var overrides = child.ToDictionary(id, StringComparer.OrdinalIgnoreCase);
        var merged = parent.Select(p => overrides.TryGetValue(id(p), out var c) ? c : p).ToList();
        merged.AddRange(child.Where(c => !parent.Any(p => string.Equals(id(p), id(c), StringComparison.OrdinalIgnoreCase))));
        return merged;
    }
}
