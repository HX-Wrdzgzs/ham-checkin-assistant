namespace HamCheckin.Native.Core.Catalogs;

public sealed class CatalogService
{
    private readonly object _publicationLock = new();
    private readonly CatalogSnapshot _builtIn;
    private readonly Func<CatalogSnapshot, string?, CancellationToken,
        Task<(CatalogSnapshot Snapshot, CatalogLoadReport Report)>> _loadExistingDataAsync;
    private CatalogSnapshot _current;
    private long _latestGeneration;

    public CatalogService()
        : this(CatalogLoader.LoadExistingDataAsync)
    {
    }

    internal CatalogService(
        Func<CatalogSnapshot, string?, CancellationToken,
            Task<(CatalogSnapshot Snapshot, CatalogLoadReport Report)>> loadExistingDataAsync)
    {
        ArgumentNullException.ThrowIfNull(loadExistingDataAsync);
        _builtIn = CatalogLoader.CreateBuiltIn();
        _current = _builtIn;
        _loadExistingDataAsync = loadExistingDataAsync;
    }

    public CatalogSnapshot Current => Volatile.Read(ref _current);

    public async Task<CatalogLoadReport> ReloadExistingDataAsync(
        string? dataRoot = null,
        CancellationToken cancellationToken = default)
    {
        long generation;
        lock (_publicationLock)
        {
            generation = ++_latestGeneration;
        }

        var (snapshot, report) = await _loadExistingDataAsync(
            _builtIn, dataRoot, cancellationToken).ConfigureAwait(false);

        lock (_publicationLock)
        {
            cancellationToken.ThrowIfCancellationRequested();
            var published = report.Succeeded && generation == _latestGeneration;
            if (published)
            {
                Volatile.Write(ref _current, snapshot);
            }

            return report with { Generation = generation, Published = published };
        }
    }
}
