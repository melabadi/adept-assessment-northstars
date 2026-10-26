using Azure.Identity;
using Azure.Storage.Blobs;
using Azure.Storage.Blobs.Models;

namespace RequestHub.Api.Storage;

/// <summary>Attachment content storage. Local disk in development, Azure Blob Storage (managed identity) in Azure.</summary>
public interface IAttachmentStore
{
    Task SaveAsync(string key, Stream content, string contentType, CancellationToken ct);
    Task<Stream?> OpenAsync(string key, CancellationToken ct);
}

public sealed class StorageSettings
{
    public const string Section = "Storage";
    /// <summary>Local (default) or Blob.</summary>
    public string Provider { get; set; } = "Local";
    public string LocalPath { get; set; } = "data/attachments";
    public string? BlobServiceUri { get; set; }
    public string Container { get; set; } = "attachments";
    public long MaxBytes { get; set; } = 5 * 1024 * 1024;
    public int MaxPerRequest { get; set; } = 10;
}

public sealed class LocalAttachmentStore(StorageSettings settings, IHostEnvironment env) : IAttachmentStore
{
    private readonly string root = Path.GetFullPath(Path.Combine(env.ContentRootPath, settings.LocalPath));

    public async Task SaveAsync(string key, Stream content, string contentType, CancellationToken ct)
    {
        var path = PathFor(key);
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        await using var file = File.Create(path);
        await content.CopyToAsync(file, ct);
    }

    public Task<Stream?> OpenAsync(string key, CancellationToken ct)
    {
        var path = PathFor(key);
        return Task.FromResult<Stream?>(File.Exists(path) ? File.OpenRead(path) : null);
    }

    private string PathFor(string key)
    {
        var full = Path.GetFullPath(Path.Combine(root, key));
        if (!full.StartsWith(root, StringComparison.Ordinal))
        {
            throw new InvalidOperationException("Invalid storage key.");
        }

        return full;
    }
}

public sealed class BlobAttachmentStore(StorageSettings settings, IConfiguration config) : IAttachmentStore
{
    private readonly BlobContainerClient container = new BlobServiceClient(
            new Uri(settings.BlobServiceUri ?? throw new InvalidOperationException("Storage:BlobServiceUri is required for the Blob provider.")),
            RequestHub.Core.Services.AzureCredentials.Create(config))
        .GetBlobContainerClient(settings.Container);

    public async Task SaveAsync(string key, Stream content, string contentType, CancellationToken ct)
    {
        await container.CreateIfNotExistsAsync(cancellationToken: ct);
        await container.GetBlobClient(key).UploadAsync(content, new BlobUploadOptions { HttpHeaders = new BlobHttpHeaders { ContentType = contentType } }, ct);
    }

    public async Task<Stream?> OpenAsync(string key, CancellationToken ct)
    {
        var blob = container.GetBlobClient(key);
        return await blob.ExistsAsync(ct) ? await blob.OpenReadAsync(cancellationToken: ct) : null;
    }
}

/// <summary>Allow-list of attachment types, checked by extension and file signature.</summary>
public static class AttachmentPolicy
{
    private static readonly Dictionary<string, (string ContentType, byte[]? Signature)> Allowed = new(StringComparer.OrdinalIgnoreCase)
    {
        [".pdf"] = ("application/pdf", "%PDF"u8.ToArray()),
        [".png"] = ("image/png", [0x89, 0x50, 0x4E, 0x47]),
        [".jpg"] = ("image/jpeg", [0xFF, 0xD8, 0xFF]),
        [".jpeg"] = ("image/jpeg", [0xFF, 0xD8, 0xFF]),
        [".txt"] = ("text/plain", null),
        [".csv"] = ("text/csv", null),
        [".docx"] = ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", [0x50, 0x4B, 0x03, 0x04]),
        [".xlsx"] = ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", [0x50, 0x4B, 0x03, 0x04]),
    };

    public static IReadOnlyCollection<string> Extensions => Allowed.Keys;

    public static string SafeFileName(string name)
    {
        var file = Path.GetFileName(name ?? "");
        var cleaned = new string(file.Where(c => !char.IsControl(c) && c is not ('"' or '\\' or '/' or ':' or '*' or '?' or '<' or '>' or '|')).ToArray()).Trim();
        if (cleaned.Length == 0)
        {
            cleaned = "attachment";
        }

        return cleaned.Length > 200 ? cleaned[^200..] : cleaned;
    }

    /// <summary>Returns the server-chosen content type, or an error message.</summary>
    public static (string? ContentType, string? Error) Check(string fileName, ReadOnlySpan<byte> head)
    {
        var ext = Path.GetExtension(fileName);
        if (!Allowed.TryGetValue(ext, out var rule))
        {
            return (null, $"File type '{ext}' is not allowed. Allowed: {string.Join(", ", Allowed.Keys)}.");
        }

        if (rule.Signature is { } signature && !head.StartsWith(signature))
        {
            return (null, $"File content does not match the '{ext}' type.");
        }

        if (rule.Signature is null && head.IndexOf((byte)0) >= 0)
        {
            return (null, "Text files must not contain binary content.");
        }

        return (rule.ContentType, null);
    }
}
