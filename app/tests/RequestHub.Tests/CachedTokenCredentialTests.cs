using Azure.Core;
using RequestHub.Core.Services;

namespace RequestHub.Tests;

/// <summary>Local runs sign in with developer credentials, which start a process per token unless RequestHub caches it.</summary>
public sealed class CachedTokenCredentialTests
{
    private static readonly TokenRequestContext Foundry = new(["https://ai.azure.com/.default"]);

    private sealed class CountingCredential(TimeSpan lifetime) : TokenCredential
    {
        public int Calls;

        public override AccessToken GetToken(TokenRequestContext requestContext, CancellationToken cancellationToken) => Next();

        public override ValueTask<AccessToken> GetTokenAsync(TokenRequestContext requestContext, CancellationToken cancellationToken) => ValueTask.FromResult(Next());

        private AccessToken Next() => new($"token-{Interlocked.Increment(ref Calls)}", DateTimeOffset.UtcNow + lifetime);
    }

    [Fact]
    public async Task Reuses_a_token_per_scope_until_shortly_before_it_expires()
    {
        var inner = new CountingCredential(TimeSpan.FromHours(1));
        var credential = new CachedTokenCredential(inner);
        var ct = TestContext.Current.CancellationToken;

        var first = await credential.GetTokenAsync(Foundry, ct);
        var second = await credential.GetTokenAsync(Foundry, ct);
        var third = credential.GetToken(Foundry, ct);
        var storage = await credential.GetTokenAsync(new TokenRequestContext(["https://storage.azure.com/.default"]), ct);

        Assert.Equal(first.Token, second.Token);
        Assert.Equal(first.Token, third.Token);
        Assert.NotEqual(first.Token, storage.Token);
        Assert.Equal(2, inner.Calls);
    }

    [Fact]
    public async Task Asks_again_when_the_token_is_about_to_expire()
    {
        var inner = new CountingCredential(TimeSpan.FromMinutes(4));
        var credential = new CachedTokenCredential(inner);
        var ct = TestContext.Current.CancellationToken;

        var first = await credential.GetTokenAsync(Foundry, ct);
        var second = await credential.GetTokenAsync(Foundry, ct);

        Assert.NotEqual(first.Token, second.Token);
        Assert.Equal(2, inner.Calls);
    }

    [Fact]
    public async Task Never_answers_a_claims_challenge_from_the_cache()
    {
        var inner = new CountingCredential(TimeSpan.FromHours(1));
        var credential = new CachedTokenCredential(inner);
        var ct = TestContext.Current.CancellationToken;
        var challenge = new TokenRequestContext(["https://ai.azure.com/.default"], claims: """{"access_token":{"nbf":{"essential":true}}}""");

        await credential.GetTokenAsync(Foundry, ct);
        var fresh = await credential.GetTokenAsync(challenge, ct);
        var again = await credential.GetTokenAsync(challenge, ct);

        Assert.NotEqual(fresh.Token, again.Token);
        Assert.Equal(3, inner.Calls);
    }
}
