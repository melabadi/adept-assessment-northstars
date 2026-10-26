using System.Globalization;
using System.Text.RegularExpressions;
using RequestHub.Core.Profiles;

namespace RequestHub.Core.Triage;

/// <summary>
/// Deterministic keyword rules over the profile's routing policies. Clearly labelled as sample logic:
/// it lets the app run without AI services and never pretends to call one.
/// </summary>
public sealed partial class SampleRulesTriageProvider : ITriageProvider
{
    public string Id => "sample-rules";

    public bool IsSample => true;

    public Task<TriageResult> RecommendAsync(TriageContext context, CancellationToken cancellationToken)
    {
        var text = $"{context.Title}\n{context.Description}".ToLowerInvariant();

        var safety = context.Policies.FirstOrDefault(p => p.Kind == "safety" && Matches(p, text));
        if (safety is not null)
        {
            return Done(safety.RouteTo, safety.Priority ?? "Urgent", [safety.Id],
                $"Sample rule: safety keywords matched, so the request is urgent for {safety.RouteTo} ({safety.Id}).", 0.8, false);
        }

        var routing = context.Policies
            .Where(p => p.Kind == "routing")
            .Select(p => (Policy: p, Score: Score(p, context.Category, text)))
            .Where(x => x.Score > 0)
            .OrderByDescending(x => x.Score)
            .ToList();

        var amount = EstimatedAmount(text);
        var spend = context.Policies.FirstOrDefault(p => p.Kind == "spend");
        var overThreshold = spend?.Threshold is { } threshold && amount > threshold;

        if (routing.Count == 0)
        {
            var fallback = context.Policies.FirstOrDefault(p => p.Kind == "fallback");
            var ids = fallback is null ? new List<string>() : [fallback.Id];
            if (overThreshold && spend is not null)
            {
                return Done(spend.RouteTo, context.CurrentPriority, [spend.Id],
                    $"Sample rule: estimated cost {amount:N0} is above {spend.Threshold:N0} ({spend.Id}).", 0.6, false);
            }

            return Done(context.CurrentDepartmentId, context.CurrentPriority, ids,
                "Sample rule: no routing keywords matched; keeping the current department for human review.", 0.3, true,
                "Which department owns this request, and what is the estimated cost?");
        }

        var best = routing[0].Policy;
        if (overThreshold && spend is not null && spend.RouteTo != best.RouteTo)
        {
            // Two policies point to different departments and neither states precedence: flag for a person.
            return Done(context.CurrentDepartmentId, context.CurrentPriority, [best.Id, spend.Id],
                $"Sample rule: {best.Id} routes to {best.RouteTo} but the estimated cost {amount:N0} triggers {spend.Id} (route to {spend.RouteTo}). Conflicting policies need a human decision.",
                0.4, true, "Should Finance review the budget before the owning department acts?");
        }

        return Done(best.RouteTo, best.Priority ?? context.CurrentPriority, [best.Id],
            $"Sample rule: matched '{best.Title}' ({best.Id}).", routing.Count == 1 ? 0.7 : 0.55, false);
    }

    private static Task<TriageResult> Done(string department, string priority, List<string> policies, string rationale,
        double confidence, bool review, string? question = null) =>
        Task.FromResult(new TriageResult(department, priority, rationale, policies, confidence, review, question));

    private static int Score(RoutingPolicy policy, string category, string text)
    {
        var score = policy.Categories.Contains(category, StringComparer.OrdinalIgnoreCase) ? 2 : 0;
        score += policy.Keywords.Count(k => text.Contains(k, StringComparison.OrdinalIgnoreCase));
        return score;
    }

    private static bool Matches(RoutingPolicy policy, string text) =>
        policy.Keywords.Any(k => text.Contains(k, StringComparison.OrdinalIgnoreCase));

    internal static decimal EstimatedAmount(string text)
    {
        decimal max = 0;
        foreach (Match m in AmountPattern().Matches(text))
        {
            var raw = m.Groups["n"].Value.Replace(",", "", StringComparison.Ordinal);
            if (decimal.TryParse(raw, NumberStyles.Number, CultureInfo.InvariantCulture, out var value))
            {
                max = Math.Max(max, value);
            }
        }

        return max;
    }

    [GeneratedRegex(@"(?:cost|est\.?|estimated|budget|quote)[^0-9]{0,20}(?<n>\d{1,3}(?:,\d{3})+|\d{4,})", RegexOptions.IgnoreCase)]
    private static partial Regex AmountPattern();
}
