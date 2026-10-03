namespace HamCheckin.Native.App.Media;

public sealed record ScreenDevice(
    int Index,
    string Name,
    int Left,
    int Top,
    int Width,
    int Height,
    bool IsPrimary)
{
    public string DisplayName =>
        $"{Name} · {Width}×{Height}{(IsPrimary ? " · 主显示器" : string.Empty)}";
}

public sealed record MicrophoneDevice(int Id, string Name)
{
    public string DisplayName => $"{Name}（设备 {Id + 1}）";
}

public sealed record RecordingOptions(
    ScreenDevice Screen,
    string OutputPath,
    bool IncludeMicrophone,
    int? MicrophoneId,
    int FramesPerSecond = 10,
    int JpegQuality = 72,
    int SampleRate = 44100);

public enum RecordingState
{
    Idle,
    Recording,
    Paused,
    Stopping,
    Completed,
    Failed
}

public sealed record RecordingResult(
    string OutputPath,
    TimeSpan Duration,
    long VideoFrames,
    long AudioBytes,
    string Format);

public sealed class RecordingStateChangedEventArgs(
    RecordingState state,
    string message,
    RecordingResult? result = null) : EventArgs
{
    public RecordingState State { get; } = state;
    public string Message { get; } = message;
    public RecordingResult? Result { get; } = result;
}

public sealed class MicrophoneLevelEventArgs(float level) : EventArgs
{
    public float Level { get; } = Math.Clamp(level, 0, 1);
}
