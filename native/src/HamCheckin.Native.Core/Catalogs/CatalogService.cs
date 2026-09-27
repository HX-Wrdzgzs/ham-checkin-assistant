namespace HamCheckin.Native.Core.Catalogs;

public sealed class CatalogService
{
    private CatalogSnapshot _current = CatalogLoader.CreateBuiltIn();

    public CatalogSnapshot Current => Volatile.Read(ref _current);

    public async Task<CatalogLoadReport> ReloadExistingDataAsync(
        string? dataRoot = null,
        CancellationToken cancellationToken = default)
    {
        var (snapshot, report) = await CatalogLoader.LoadExistingDataAsync(
            Current, dataRoot, cancellationToken).ConfigureAwait(false);
        Volatile.Write(ref _current, snapshot);
        return report;
    }
}
