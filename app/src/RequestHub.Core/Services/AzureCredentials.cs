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
            ? new DefaultAzureCredential(new DefaultAzureCredentialOptions { ExcludeManagedIdentityCredential = true })
            : new ManagedIdentityCredential(ManagedIdentityId.FromUserAssignedClientId(clientId));
    }
}
