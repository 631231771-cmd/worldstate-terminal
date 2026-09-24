using System.ComponentModel;
using System.IO;
using System.Net.WebSockets;
using System.Text;
using System.Text.Json;
using ATAS.Indicators;

namespace WorldState.AtasBridge;

/// <summary>
/// Opt-in, display-only snapshot exporter for ONE GC chart.
/// When the SDK only exposes GC, the contract month stays unverified.
/// No orders, history, DOM, Rithmic login, quote file output, or remote network access.
/// Lifecycle diagnostics are written to a small, bounded local log.
/// </summary>
[DisplayName("WorldState Bridge (GC)")]
public sealed class WorldStateBridge : Indicator
{
    private const string Endpoint = "ws://127.0.0.1:8000/v2/product/local-bridge/gc";
    private static readonly Uri BridgeUri = new(Endpoint);
    private static readonly System.Text.RegularExpressions.Regex ContractPattern =
        new(@"^#?(GC[FGHJKMNQUVXZ]\d{1,4})$", System.Text.RegularExpressions.RegexOptions.CultureInvariant);
    private readonly object _gate = new();
    private CancellationTokenSource? _stop;
    private Task? _sender;
    private string? _contract;
    private string? _sourceSymbol;
    private string? _exchange;
    private DateTime? _eventAt;
    private DateTime? _tradeAt;
    private decimal? _lastTrade;
    private decimal? _bid;
    private decimal? _ask;
    private decimal? _tradeVolume;
    private MinuteBar? _bar;
    private bool _enabled;
    private readonly string _diagnosticId = Guid.NewGuid().ToString("N")[..8];
    private readonly Dictionary<string, string> _diagnosticStates = new();
    private static readonly object DiagnosticFileGate = new();

    // Bounded local lifecycle diagnostics only: no credentials or quote history.
    private void Diagnostic(string area, string detail)
    {
        try
        {
            lock (_diagnosticStates)
            {
                if (_diagnosticStates.GetValueOrDefault(area) == detail) return;
                _diagnosticStates[area] = detail;
            }
            var directory = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "WorldStateTerminal", "logs");
            lock (DiagnosticFileGate)
            {
                Directory.CreateDirectory(directory);
                var path = Path.Combine(directory, "atas-gc-bridge.log");
                if (File.Exists(path) && new FileInfo(path).Length >= 131072) return;
                File.AppendAllText(path, $"{DateTime.UtcNow:O} diag-v1 {_diagnosticId} {area}: {detail}{Environment.NewLine}");
            }
        }
        catch { /* Diagnostics must never interrupt the chart. */ }
    }

    private static string DiagnosticSymbol(string? symbol) => symbol is null ? "<null>" :
        new string(symbol.Take(80).Where(c => char.IsLetterOrDigit(c) || "#@()._- ".Contains(c)).ToArray());

    [DisplayName("Enable local GC bridge")]
    [Description("Off by default. Also requires ATAS_LIVE_BRIDGE_ENABLED=1 in WorldState Research API.")]
    public bool EnableLocalBridge
    {
        get => _enabled;
        set
        {
            if (_enabled == value) return;
            _enabled = value;
            Diagnostic("enabled", value.ToString());
            if (value) TryStart();
            else
            {
                lock (_gate)
                {
                    _stop?.Cancel();
                    _stop = null;
                    _eventAt = _tradeAt = null;
                    _lastTrade = _bid = _ask = _tradeVolume = null;
                    _bar = null;
                }
            }
        }
    }

    public WorldStateBridge() : base(true) { }

    protected override void OnInitialize()
    {
        Diagnostic("lifecycle", "initialized");
        TryStart();
    }

    protected override void OnCalculate(int bar, decimal value) => TryStart();

    private string? CurrentChartSymbol()
    {
        // The SDK can expose only the GC root even when the toolbar shows a
        // dated contract. Never turn that root into a guessed contract month.
#pragma warning disable CS0618 // Legacy chart symbol is only a dated-contract fallback.
        var candidates = new[] { InstrumentInfo?.Instrument, Instrument };
#pragma warning restore CS0618
        foreach (var candidate in candidates)
        {
            if (candidate is not null && ContractPattern.IsMatch(candidate))
                return candidate;
        }
        return candidates.Contains("GC") ? "GC" : null;
    }

    private void TryStart()
    {
        // ATAS may apply saved indicator properties after OnInitialize. The first
        // calculation is a second chance, without any historical export.
        if (!EnableLocalBridge || _stop is not null) return;
        lock (_gate)
        {
            if (_stop is not null) return;
            var instrument = CurrentChartSymbol();
            var contractMatch = instrument is null ? null : ContractPattern.Match(instrument);
            if (instrument is null)
            {
#pragma warning disable CS0618
                Diagnostic("contract", $"rejected info={DiagnosticSymbol(InstrumentInfo?.Instrument)} legacy={DiagnosticSymbol(Instrument)} provider={(DataProvider is null ? "absent" : "present")}");
#pragma warning restore CS0618
                return; // Unknown symbols and non-GC charts fail closed.
            }
            Diagnostic("contract", contractMatch?.Success == true
                ? $"accepted dated {DiagnosticSymbol(instrument)}"
                : "accepted GC root; contract month unverified");
            _sourceSymbol = instrument;
            _contract = contractMatch?.Success == true ? contractMatch.Groups[1].Value : null;
            _exchange = InstrumentInfo?.Exchange;
            var stop = new CancellationTokenSource();
            _stop = stop;
            _sender = Task.Run(() => SendLoop(stop.Token));
        }
    }

    protected override void OnNewTrade(MarketDataArg arg)
    {
        if (EnableLocalBridge) Diagnostic("trade_callback", $"received type={arg.DataType} time_kind={arg.Time.Kind}");
        // A chart can apply indicator properties after its initial calculation;
        // the first live callback is another chance to start without replay.
        if (EnableLocalBridge && _stop is null) TryStart();
        if (!EnableLocalBridge || _stop is null || !string.Equals(arg.DataType.ToString(), "Trade", StringComparison.Ordinal))
            return;
        if (!TryUtc(arg.Time, out var at) || arg.Price <= 0 || arg.Volume < 0)
        {
            Diagnostic("trade_validation", "rejected timestamp or price/volume");
            return;
        }
        Diagnostic("trade_validation", "accepted");
        lock (_gate)
        {
            if (_tradeAt.HasValue && at < _tradeAt.Value) return;
            _eventAt = at;
            _tradeAt = at;
            _lastTrade = arg.Price;
            _tradeVolume = arg.Volume;
            var minute = new DateTime(at.Year, at.Month, at.Day, at.Hour, at.Minute, 0, DateTimeKind.Utc);
            if (_bar is null || minute > _bar.Start)
                _bar = new MinuteBar(minute, arg.Price, arg.Volume);
            else if (minute == _bar.Start)
                _bar.Apply(arg.Price, arg.Volume);
        }
    }

    protected override void OnBestBidAskChanged(MarketDataArg arg)
    {
        if (EnableLocalBridge && _stop is null) TryStart();
        if (!EnableLocalBridge || _stop is null || !TryUtc(arg.Time, out var at) || arg.Price <= 0)
            return;
        var kind = arg.DataType.ToString();
        if (kind is not ("Bid" or "Ask")) return;
        lock (_gate)
        {
            if (_eventAt.HasValue && at < _eventAt.Value) return;
            _eventAt = at;
            if (kind == "Bid") _bid = arg.Price;
            else _ask = arg.Price;
        }
    }

    private bool TryUtc(DateTime input, out DateTime utc)
    {
        utc = input.Kind switch
        {
            DateTimeKind.Utc => input,
            DateTimeKind.Local => input.ToUniversalTime(),
            // ATAS documents market timestamps as UTC, but leaves Kind unspecified.
            // Accept only when the raw clock agrees with ATAS's own UTC clock.
            _ => DateTime.SpecifyKind(input, DateTimeKind.Utc)
        };
        return Math.Abs((UtcTime - utc).TotalMinutes) <= 2;
    }

    private object? Capture()
    {
        lock (_gate)
        {
            if (!EnableLocalBridge || _sourceSymbol is null || !_eventAt.HasValue || !_lastTrade.HasValue || !_tradeAt.HasValue)
                return null;
            if (CurrentChartSymbol() != _sourceSymbol)
                return null; // Stop when the SDK chart identity changes.
            if ((DateTime.UtcNow - _eventAt.Value).TotalSeconds > 30)
                return null; // Do not heartbeat an old price as live.
            return new
            {
                schema_version = 1,
                symbol = "GC",
                contract = _contract,
                source_symbol = _sourceSymbol,
                exchange = _exchange,
                event_timestamp = _eventAt.Value,
                last_trade_timestamp = _tradeAt.Value,
                last_trade = _lastTrade,
                best_bid = _bid.HasValue && _ask.HasValue && _bid > _ask ? null : _bid,
                best_ask = _bid.HasValue && _ask.HasValue && _bid > _ask ? null : _ask,
                last_trade_volume = _tradeVolume,
                bar_1m = _bar is null ? null : new
                {
                    start = _bar.Start,
                    open = _bar.Open,
                    high = _bar.High,
                    low = _bar.Low,
                    close = _bar.Close,
                    volume = _bar.Volume
                }
            };
        }
    }

    private async Task SendLoop(CancellationToken stop)
    {
        while (!stop.IsCancellationRequested)
        {
            try
            {
                using var socket = new ClientWebSocket();
                Diagnostic("socket", "connecting");
                await socket.ConnectAsync(BridgeUri, stop);
                Diagnostic("socket", "connected");
                while (socket.State == WebSocketState.Open && !stop.IsCancellationRequested)
                {
                    var snapshot = Capture();
                    if (snapshot is not null)
                    {
                        var bytes = Encoding.UTF8.GetBytes(JsonSerializer.Serialize(snapshot));
                        await socket.SendAsync(bytes, WebSocketMessageType.Text, true, stop);
                        Diagnostic("snapshot", "sent");
                    }
                    else Diagnostic("snapshot", "waiting for current valid trade");
                    await Task.Delay(1000, stop); // bounded 1 snapshot/sec, no tick history
                }
            }
            catch (OperationCanceledException) when (stop.IsCancellationRequested) { break; }
            catch (Exception exception)
            {
                // ATAS chart must remain usable if WorldState is closed or restarted.
                Diagnostic("socket_error", $"{exception.GetType().Name} hresult={exception.HResult}");
            }
            try { await Task.Delay(3000, stop); }
            catch (OperationCanceledException) { break; }
        }
    }

    protected override void OnDispose()
    {
        Diagnostic("lifecycle", "disposed");
        _stop?.Cancel();
        base.OnDispose();
    }

    private sealed class MinuteBar(DateTime start, decimal first, decimal volume)
    {
        public DateTime Start { get; } = start;
        public decimal Open { get; } = first;
        public decimal High { get; private set; } = first;
        public decimal Low { get; private set; } = first;
        public decimal Close { get; private set; } = first;
        public decimal Volume { get; private set; } = volume;

        public void Apply(decimal price, decimal size)
        {
            High = Math.Max(High, price);
            Low = Math.Min(Low, price);
            Close = price;
            Volume += size;
        }
    }
}
