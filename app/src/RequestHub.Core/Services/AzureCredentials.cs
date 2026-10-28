using System.Collections.Concurrent;
using Azure.Core;
using Azure.Identity;
using Microsoft.Extensions.Configuration;

namespace RequestHub.Core.Services;

/// <summary>
/// One place that decides how RequestHub authenticates to Azure services (PostgreSQL, Blob Storage, Foundry).
/// In Azure, AZURE_CLIENT_ID names the app's user-assigned managed identity. Locally it is unset, so developer
/// credentials (az login, azd login, Visual Studio) are used and the slow managed-identity probe is skipped.
/// </summary>
public static class AzureCredentials
{
    public static TokenCredential Create(IConfiguration config)
    {
        var clientId = config["AZURE_CLIENT_ID"];
        return string.IsNullOrWhiteSpace(clientId)
            ? new CachedTokenCredential(new DefaultAzureCredential(new DefaultAzureCredentialOptions { ExcludeManagedIdentityCredential = true }))
            : new ManagedIdentityCredential(ManagedIdentityId.FromUserAssignedClientId(clientId));
    }
}

/// <summary>
/// Reuses each token until five minutes before it expires. Developer credentials do not cache tokens: the Azure CLI
/// credential starts a process for every token, which can take more than ten seconds, and the Foundry client asks for a
/// token on every request. Managed identity caches its tokens itself, so it is not wrapped.
/// </summary>
public sealed class CachedTokenCredential(TokenCredential inner) : TokenCredential
{
    private static readonly TimeSpan RefreshMargin = TimeSpan.FromMinutes(5);
    private readonly ConcurrentDictionary<string, AccessToken> tokens = new();

    public override AccessToken GetToken(TokenRequestContext requestContext, CancellationToken cancellationToken)
    {
        var key = Key(requestContext);
        return Cached(key) ?? Store(key, inner.GetToken(requestContext, cancellationToken));
    }

    public override async ValueTask<AccessToken> GetTokenAsync(TokenRequestContext requestContext, CancellationToken cancellationToken)
    {
        var key = Key(requestContext);
        return Cached(key) ?? Store(key, await inner.GetTokenAsync(requestContext, cancellationToken).ConfigureAwait(false));
    }

    // A claims challenge asks for a new token, so it never gets a cached one.
    private static string? Key(TokenRequestContext context) =>
        string.IsNullOrEmpty(context.Claims) ? $"{context.TenantId}|{string.Join(' ', context.Scopes)}" : null;

    private AccessToken? Cached(string? key) =>
        key is not null && tokens.TryGetValue(key, out var token) && token.ExpiresOn - RefreshMargin > DateTimeOffset.UtcNow ? token : null;

    private AccessToken Store(string? key, AccessToken token)
    {
        if (key is not null)
        {
            tokens[key] = token;
        }

        return token;
    }
}
