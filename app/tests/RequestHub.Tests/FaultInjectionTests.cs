using System.Diagnostics;
using System.Net;

namespace RequestHub.Tests;

public sealed class ActiveQueueDelayFixture : ApiFixture
{
    protected override IReadOnlyDictionary<string, string> Settings { get; } = new Dictionary<string, string>
    {
        ["Faults:QueueDelayMs"] = "1500",
        ["Faults:ExpiresAtUtc"] = DateTimeOffset.UtcNow.AddMinutes(30).ToString("O"),
    };
}

public sealed class ExpiredQueueDelayFixture : ApiFixture
{
    protected override IReadOnlyDictionary<string, string> Settings { get; } = new Dictionary<string, string>
    {
        ["Faults:QueueDelayMs"] = "10000",
        ["Faults:ExpiresAtUtc"] = DateTimeOffset.UtcNow.AddMinutes(-1).ToString("O"),
    };
}

/// <summary>The Test · Microsoft load test relies on this fault to rehearse a slowdown, and on its expiry to recover.</summary>
public sealed class ActiveQueueDelayTests(ActiveQueueDelayFixture api) : IClassFixture<ActiveQueueDelayFixture>
{
    [Fact]
    public async Task Active_queue_delay_slows_the_request_list_but_not_request_details()
    {
        var client = api.As("u-ben");
        var list = Stopwatch.StartNew();
        Assert.Equal(HttpStatusCode.OK, (await client.GetAsync("/api/requests?scope=queue")).StatusCode);
        list.Stop();
        Assert.True(list.ElapsedMilliseconds >= 1500, $"list took {list.ElapsedMilliseconds} ms");

        var detail = Stopwatch.StartNew();
        Assert.Equal(HttpStatusCode.OK, (await client.GetAsync("/api/requests/REQ-1001")).StatusCode);
        detail.Stop();
        Assert.True(detail.ElapsedMilliseconds < 1500, $"detail took {detail.ElapsedMilliseconds} ms");
    }
}

public sealed class ExpiredQueueDelayTests(ExpiredQueueDelayFixture api) : IClassFixture<ExpiredQueueDelayFixture>
{
    [Fact]
    public async Task Expired_queue_delay_is_ignored()
    {
        var watch = Stopwatch.StartNew();
        Assert.Equal(HttpStatusCode.OK, (await api.As("u-ben").GetAsync("/api/requests?scope=queue")).StatusCode);
        watch.Stop();
        Assert.True(watch.ElapsedMilliseconds < 10000, $"list took {watch.ElapsedMilliseconds} ms");
    }
}
