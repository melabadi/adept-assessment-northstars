using System.Security.Claims;
using System.Text;
using System.Text.Encodings.Web;
using System.Text.Json;
using System.Text.Json.Serialization;
using Microsoft.AspNetCore.Authentication;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Options;
using RequestHub.Core.Data;
using RequestHub.Core.Domain;
using RequestHub.Core.Services;

namespace RequestHub.Api.Auth;

public sealed class AuthSettings
{
    public const string Section = "Auth";
    public const string DevelopmentMode = "Development";
    public const string EasyAuthMode = "EasyAuth";

    /// <summary>Development (local persona switcher, fails closed elsewhere) or EasyAuth (Azure Container Apps + Entra ID).</summary>
    public string Mode { get; set; } = DevelopmentMode;
    /// <summary>App-role values in Entra tokens are expected as {RolePrefix}{Role}, e.g. RequestHub.Approver.</summary>
    public string RolePrefix { get; set; } = "RequestHub.";
    /// <summary>Department access granted to signed-in reviewers/approvers unless overridden per principal.</summary>
    public string DefaultDepartmentAccess { get; set; } = "IT,FAC,FIN,HR,OPS";
    public string DefaultHomeDepartment { get; set; } = "OPS";
    /// <summary>Per-principal department access override: object id -> comma-separated departments.</summary>
    public Dictionary<string, string> PrincipalDepartments { get; set; } = [];
}

public static class RequestHubClaims
{
    public const string Department = "rh:dept";
    public const string HomeDepartment = "rh:home";

    public static AppUser ToAppUser(this ClaimsPrincipal principal) => new(
        principal.FindFirstValue(ClaimTypes.NameIdentifier) ?? throw new InvalidOperationException("Unauthenticated."),
        principal.FindFirstValue(ClaimTypes.Name) ?? "Unknown",
        principal.FindAll(ClaimTypes.Role).Select(c => c.Value).ToHashSet(StringComparer.Ordinal),
        principal.FindAll(Department).Select(c => c.Value).ToHashSet(StringComparer.Ordinal),
        principal.FindFirstValue(HomeDepartment) ?? "OPS");

    public static ClaimsPrincipal FromUser(User user, string scheme)
    {
        var claims = new List<Claim>
        {
            new(ClaimTypes.NameIdentifier, user.Id),
            new(ClaimTypes.Name, user.DisplayName),
            new(HomeDepartment, user.HomeDepartmentId),
        };
        claims.AddRange(user.Roles.Select(r => new Claim(ClaimTypes.Role, r)));
        claims.AddRange(user.DepartmentAccess.Select(d => new Claim(Department, d)));
        return new ClaimsPrincipal(new ClaimsIdentity(claims, scheme));
    }
}

/// <summary>
/// Local development only: the caller picks a synthetic persona with the X-RequestHub-User header or rh_user cookie.
/// Program.cs refuses to start in this mode outside Development/Testing environments.
/// </summary>
public sealed class DevPersonaAuthHandler(
    IOptionsMonitor<AuthenticationSchemeOptions> options,
    ILoggerFactory logger,
    UrlEncoder encoder,
    RequestHubDbContext db) : AuthenticationHandler<AuthenticationSchemeOptions>(options, logger, encoder)
{
    public const string SchemeName = "DevPersona";
    public const string Header = "X-RequestHub-User";
    public const string Cookie = "rh_user";

    protected override async Task<AuthenticateResult> HandleAuthenticateAsync()
    {
        var id = Request.Headers[Header].FirstOrDefault() ?? Request.Cookies[Cookie];
        if (string.IsNullOrWhiteSpace(id))
        {
            return AuthenticateResult.NoResult();
        }

        var user = await db.Users.AsNoTracking().FirstOrDefaultAsync(u => u.Id == id && u.IsSynthetic, Context.RequestAborted);
        return user is null
            ? AuthenticateResult.Fail($"Unknown persona '{id}'.")
            : AuthenticateResult.Success(new AuthenticationTicket(RequestHubClaims.FromUser(user, SchemeName), SchemeName));
    }
}

/// <summary>
/// Azure Container Apps built-in authentication (Easy Auth) validates the Entra ID session or bearer token and
/// forwards the caller as the X-MS-CLIENT-PRINCIPAL header. The platform does not enforce app roles, so this
/// handler maps them and the workflow enforces them. Only enable this mode when platform auth is configured.
/// </summary>
public sealed class EasyAuthHandler(
    IOptionsMonitor<AuthenticationSchemeOptions> options,
    ILoggerFactory logger,
    UrlEncoder encoder,
    RequestHubDbContext db,
    IOptions<AuthSettings> settings) : AuthenticationHandler<AuthenticationSchemeOptions>(options, logger, encoder)
{
    public const string SchemeName = "EasyAuth";
    public const string PrincipalHeader = "X-MS-CLIENT-PRINCIPAL";
    private const string ObjectIdClaim = "http://schemas.microsoft.com/identity/claims/objectidentifier";

    protected override async Task<AuthenticateResult> HandleAuthenticateAsync()
    {
        var header = Request.Headers[PrincipalHeader].FirstOrDefault();
        if (string.IsNullOrEmpty(header))
        {
            return AuthenticateResult.NoResult();
        }

        ClientPrincipal? principal;
        try
        {
            principal = JsonSerializer.Deserialize<ClientPrincipal>(Convert.FromBase64String(header));
        }
        catch (Exception ex) when (ex is FormatException or JsonException)
        {
            return AuthenticateResult.Fail("Malformed client principal.");
        }

        var claims = principal?.Claims ?? [];
        string? Claim(params string[] types) => claims.FirstOrDefault(c => types.Contains(c.Type, StringComparer.OrdinalIgnoreCase))?.Value;

        var objectId = Claim(ObjectIdClaim, "oid");
        if (string.IsNullOrEmpty(objectId))
        {
            return AuthenticateResult.Fail("Client principal has no object id.");
        }

        var cfg = settings.Value;
        var roleType = principal!.RoleType ?? "roles";
        var roles = claims.Where(c => c.Type == roleType || c.Type == "roles" || c.Type == ClaimTypes.Role)
            .Select(c => c.Value.StartsWith(cfg.RolePrefix, StringComparison.Ordinal) ? c.Value[cfg.RolePrefix.Length..] : c.Value)
            .Where(r => Roles.All.Contains(r))
            .Distinct().ToList();
        var name = Claim("name", principal.NameType ?? "name", "preferred_username") ?? $"App {Claim("appid", "azp") ?? objectId}";
        var departments = (cfg.PrincipalDepartments.TryGetValue(objectId, out var custom) ? custom : cfg.DefaultDepartmentAccess)
            .Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries).ToList();

        var userId = $"aad-{objectId}";
        var displayName = name.Length > 120 ? name[..120] : name;
        var access = roles.Any(r => r is Roles.Reviewer or Roles.Approver or Roles.Admin) ? departments : [];
        var user = await db.Users.FirstOrDefaultAsync(u => u.Id == userId, Context.RequestAborted);
        if (user is null)
        {
            user = new User { Id = userId, DisplayName = displayName, HomeDepartmentId = cfg.DefaultHomeDepartment, ExternalId = objectId, Roles = roles, DepartmentAccess = access };
            db.Users.Add(user);
            try
            {
                await db.SaveChangesAsync(Context.RequestAborted);
            }
            catch (DbUpdateException)
            {
                // A concurrent first request created the same user; use that row.
                db.ChangeTracker.Clear();
                user = await db.Users.FirstAsync(u => u.Id == userId, Context.RequestAborted);
            }
        }

        if (user.DisplayName != displayName || !user.Roles.SequenceEqual(roles) || !user.DepartmentAccess.SequenceEqual(access))
        {
            user.DisplayName = displayName;
            user.Roles = roles;
            user.DepartmentAccess = access;
            await db.SaveChangesAsync(Context.RequestAborted);
        }

        return AuthenticateResult.Success(new AuthenticationTicket(RequestHubClaims.FromUser(user, SchemeName), SchemeName));
    }

    private sealed class ClientPrincipal
    {
        [JsonPropertyName("auth_typ")] public string? AuthType { get; set; }
        [JsonPropertyName("name_typ")] public string? NameType { get; set; }
        [JsonPropertyName("role_typ")] public string? RoleType { get; set; }
        [JsonPropertyName("claims")] public List<ClientClaim> Claims { get; set; } = [];
    }

    private sealed class ClientClaim
    {
        [JsonPropertyName("typ")] public string Type { get; set; } = "";
        [JsonPropertyName("val")] public string Value { get; set; } = "";
    }
}

public static class AuthSetup
{
    private static readonly string[] DevelopmentEnvironments = ["Development", "Testing", "Local"];

    public static void AddRequestHubAuth(this WebApplicationBuilder builder)
    {
        builder.Services.Configure<AuthSettings>(builder.Configuration.GetSection(AuthSettings.Section));
        var mode = builder.Configuration[$"{AuthSettings.Section}:Mode"] ?? AuthSettings.DevelopmentMode;

        if (mode == AuthSettings.DevelopmentMode)
        {
            // Fail closed: the persona switcher must never run in a shared or cloud environment.
            if (!DevelopmentEnvironments.Contains(builder.Environment.EnvironmentName))
            {
                throw new InvalidOperationException(
                    $"Auth:Mode=Development is only allowed in {string.Join("/", DevelopmentEnvironments)} environments, not '{builder.Environment.EnvironmentName}'. Configure Auth:Mode=EasyAuth.");
            }

            builder.Services.AddAuthentication(DevPersonaAuthHandler.SchemeName)
                .AddScheme<AuthenticationSchemeOptions, DevPersonaAuthHandler>(DevPersonaAuthHandler.SchemeName, null);
        }
        else if (mode == AuthSettings.EasyAuthMode)
        {
            builder.Services.AddAuthentication(EasyAuthHandler.SchemeName)
                .AddScheme<AuthenticationSchemeOptions, EasyAuthHandler>(EasyAuthHandler.SchemeName, null);
        }
        else
        {
            throw new InvalidOperationException($"Unknown Auth:Mode '{mode}'. Use Development or EasyAuth.");
        }

        builder.Services.AddAuthorizationBuilder()
            .SetFallbackPolicy(null)
            .AddPolicy("Admin", p => p.RequireRole(Roles.Admin));
    }

    /// <summary>
    /// CSRF guard: unsafe requests without a bearer token must carry a custom header, which a cross-site form cannot send.
    /// </summary>
    public static IApplicationBuilder UseCustomHeaderCsrfGuard(this IApplicationBuilder app) => app.Use(async (ctx, next) =>
    {
        var method = ctx.Request.Method;
        var unsafeMethod = HttpMethods.IsPost(method) || HttpMethods.IsPut(method) || HttpMethods.IsPatch(method) || HttpMethods.IsDelete(method);
        if (unsafeMethod && ctx.Request.Path.StartsWithSegments("/api")
            && !ctx.Request.Headers.Authorization.Any()
            && !ctx.Request.Headers.ContainsKey(DevPersonaAuthHandler.Header)
            && !ctx.Request.Headers.ContainsKey("X-RequestHub-Client"))
        {
            await Results.Problem(
                    statusCode: StatusCodes.Status400BadRequest,
                    title: "request.missing_client_header",
                    detail: "Send the X-RequestHub-Client header with state-changing requests.",
                    extensions: new Dictionary<string, object?> { ["code"] = "request.missing_client_header" })
                .ExecuteAsync(ctx);
            return;
        }

        await next();
    });

    public static string ModeName(IConfiguration config) => config[$"{AuthSettings.Section}:Mode"] ?? AuthSettings.DevelopmentMode;

    internal static string Base64Principal(object principal) =>
        Convert.ToBase64String(Encoding.UTF8.GetBytes(JsonSerializer.Serialize(principal)));
}
