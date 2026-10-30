using System.Diagnostics;
using System.Text.Json;
using Azure.AI.Extensions.OpenAI;
using Azure.Core;
using Microsoft.Extensions.Options;
using OpenAI.Responses;
using RequestHub.Core.Services;
using RequestHub.Core.Triage;

namespace RequestHub.Api.Triage;

public sealed class FoundrySettings
{
    public const string Section = "Foundry";
    /// <summary>https://&lt;account&gt;.services.ai.azure.com/api/projects/&lt;project&gt;</summary>
    public string? ProjectEndpoint { get; set; }
    /// <summary>Name of the Foundry prompt agent to call. It must already exist in the project at ProjectEndpoint.</summary>
    public string AgentName { get; set; } = "requesthub-triage";
    /// <summary>Pin a version, or leave empty to use the agent's latest version.</summary>
    public string? AgentVersion { get; set; }
    public int MaxToolRounds { get; set; } = 4;
}

/// <summary>
/// Live triage provider backed by a Microsoft Foundry agent (Develop phase, Microsoft track).
/// The agent only sees a request id; it must call the app's tools to read permitted fields and policies.
/// Tools run here, inside the API, with the caller's authorization and an audit entry per call.
/// The agent has no tool that can approve, reject, or change a request.
/// </summary>
public sealed class FoundryTriageProvider(IOptions<FoundrySettings> options, TokenCredential credential, ILogger<FoundryTriageProvider> logger) : ITriageProvider
{
    private static readonly JsonSerializerOptions Json = new(JsonSerializerDefaults.Web);
    private ProjectResponsesClient? client;

    public string Id => "foundry-agent";

    public bool IsSample => false;

    public async Task<TriageResult> RecommendAsync(TriageContext context, CancellationToken cancellationToken)
    {
        var settings = options.Value;
        if (string.IsNullOrWhiteSpace(settings.ProjectEndpoint))
        {
            throw new TriageUnavailableException("Foundry:ProjectEndpoint is not configured.");
        }

        client ??= new ProjectResponsesClient(new Uri(settings.ProjectEndpoint), credential,
            new AgentReference(settings.AgentName, string.IsNullOrWhiteSpace(settings.AgentVersion) ? null : settings.AgentVersion), null, null);

        using var activity = RequestHubTelemetry.ActivitySource.StartActivity("foundry.agent.triage");
        activity?.SetTag("gen_ai.agent.name", settings.AgentName);
        var prompt = JsonSerializer.Serialize(new
        {
            task = "Recommend routing for this RequestHub request. Read it with get_request and every policy with get_routing_policies (category null) before answering.",
            requestId = context.RequestId,
            category = context.Category,
            departments = context.Departments.Select(d => new { id = d.Id, name = d.Name }),
        }, Json);

        ResponseResult response;
        var toolCalls = 0;
        try
        {
            response = (await client.CreateResponseAsync([ResponseItem.CreateUserMessageItem(prompt)], previousResponseId: null, cancellationToken)).Value;
            for (var round = 0; round < settings.MaxToolRounds; round++)
            {
                var calls = response.OutputItems.OfType<FunctionCallResponseItem>().ToList();
                if (calls.Count == 0)
                {
                    break;
                }

                var outputs = new List<ResponseItem>();
                foreach (var call in calls)
                {
                    toolCalls++;
                    outputs.Add(ResponseItem.CreateFunctionCallOutputItem(call.CallId, await ExecuteToolAsync(call, context.Tools, cancellationToken)));
                }

                response = (await client.CreateResponseAsync(outputs, previousResponseId: response.Id, cancellationToken)).Value;
            }
        }
        catch (OperationCanceledException)
        {
            throw;
        }
        catch (Exception ex) when (ex is System.ClientModel.ClientResultException or Azure.RequestFailedException or HttpRequestException or Azure.Identity.AuthenticationFailedException)
        {
            logger.LogWarning(ex, "Foundry agent {Agent} call failed", settings.AgentName);
            throw new TriageUnavailableException($"Foundry agent call failed: {ex.Message}", ex);
        }

        activity?.SetTag("gen_ai.response.id", response.Id);
        activity?.SetTag("requesthub.triage.tool_calls", toolCalls);
        if (toolCalls == 0)
        {
            // A recommendation that never read the request is a guess; do not accept it.
            throw new TriageInvalidOutputException("the agent answered without calling get_request.");
        }

        AgentOutput? output;
        try
        {
            output = ParseOutput(response.GetOutputText(), out var answers);
            if (answers > 1)
            {
                logger.LogWarning("Foundry agent {Agent} returned {Count} JSON answers in response {ResponseId}; using the last one", settings.AgentName, answers, response.Id);
            }
        }
        catch (JsonException ex)
        {
            throw new TriageInvalidOutputException($"response {response.Id} is not valid JSON ({ex.Message}).");
        }

        if (output is null || string.IsNullOrWhiteSpace(output.SuggestedDepartmentId) || output.PolicyIds is null)
        {
            throw new TriageInvalidOutputException($"response {response.Id} is missing required fields.");
        }

        logger.LogInformation("Foundry agent {Agent} recommended {Department} for {RequestId} (response {ResponseId}, {ToolCalls} tool calls)",
            settings.AgentName, output.SuggestedDepartmentId, context.RequestId, response.Id, toolCalls);
        return new TriageResult(output.SuggestedDepartmentId, output.SuggestedPriority ?? context.CurrentPriority, output.Rationale ?? "",
            output.PolicyIds, output.Confidence, output.NeedsHumanReview, output.ClarifyingQuestion, response.Id);
    }

    private static async Task<string> ExecuteToolAsync(FunctionCallResponseItem call, ITriageTools tools, CancellationToken ct)
    {
        using var args = JsonDocument.Parse(call.FunctionArguments.ToString());
        string? Arg(string name) => args.RootElement.TryGetProperty(name, out var v) && v.ValueKind == JsonValueKind.String ? v.GetString() : null;
        return call.FunctionName switch
        {
            "get_request" => await tools.GetRequestAsync(Arg("request_id") ?? "", ct),
            "get_routing_policies" => await tools.GetRoutingPoliciesAsync(Arg("category"), ct),
            _ => JsonSerializer.Serialize(new { error = "unknown_tool", message = $"Tool '{call.FunctionName}' is not available." }),
        };
    }

    /// <summary>
    /// Reads the agent's JSON answer. The model occasionally emits the answer twice in one response ("{...}{...}"),
    /// so the reader accepts several top-level values and the last complete object wins.
    /// </summary>
    internal static AgentOutput? ParseOutput(string text, out int answers)
    {
        var reader = new Utf8JsonReader(System.Text.Encoding.UTF8.GetBytes(text), new JsonReaderOptions { AllowMultipleValues = true });
        AgentOutput? last = null;
        answers = 0;
        while (reader.Read())
        {
            if (reader.TokenType != JsonTokenType.StartObject)
            {
                throw new JsonException($"expected a JSON object, found {reader.TokenType}");
            }

            last = JsonSerializer.Deserialize<AgentOutput>(ref reader, Json);
            answers++;
        }

        return last;
    }

    internal sealed record AgentOutput(
        string SuggestedDepartmentId,
        string? SuggestedPriority,
        string? Rationale,
        List<string>? PolicyIds,
        double Confidence,
        bool NeedsHumanReview,
        string? ClarifyingQuestion);
}
