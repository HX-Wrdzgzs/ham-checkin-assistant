using System.IO;

namespace HamCheckin.Native.App.Media;

/// <summary>
/// Coordinates screen frames, microphone PCM and the AVI writer.  The service
/// deliberately keeps all capture work off the WPF dispatcher thread.
/// </summary>
public sealed class ScreenRecordingService : IDisposable
{
    private readonly object _gate = new();
    private CancellationTokenSource? _captureCancellation;
    private Task? _captureTask;
    private AviFileWriter? _writer;
    private MicrophoneCapture? _microphone;
    private RecordingOptions? _options;
    private DateTimeOffset _startedAt;
    private RecordingState _state = RecordingState.Idle;
    private string _failureMessage = string.Empty;
    private RecordingResult? _lastResult;
    private long _lastVideoFrames;
    private long _lastAudioBytes;
    private string _lastOutputPath = string.Empty;

    public event EventHandler<RecordingStateChangedEventArgs>? StateChanged;
    public event EventHandler<MicrophoneLevelEventArgs>? LevelChanged;

    public RecordingState State
    {
        get
        {
            lock (_gate)
            {
                return _state;
            }
        }
    }

    public string OutputPath
    {
        get
        {
            lock (_gate)
            {
                return _options?.OutputPath ?? _lastOutputPath;
            }
        }
    }

    public TimeSpan Elapsed
    {
        get
        {
            lock (_gate)
            {
                return _startedAt == default
                    ? _lastResult?.Duration ?? TimeSpan.Zero
                    : DateTimeOffset.Now - _startedAt;
            }
        }
    }

    public long VideoFrames => _writer?.VideoFrames ?? Interlocked.Read(ref _lastVideoFrames);
    public long AudioBytes => _writer?.AudioBytes ?? Interlocked.Read(ref _lastAudioBytes);
    public bool IsActive => State is RecordingState.Recording or RecordingState.Paused or RecordingState.Stopping;

    public void Start(RecordingOptions options)
    {
        ArgumentNullException.ThrowIfNull(options);
        var normalized = options with
        {
            FramesPerSecond = Math.Clamp(options.FramesPerSecond, 1, 30),
            JpegQuality = Math.Clamp(options.JpegQuality, 40, 95)
        };

        AviFileWriter? writer = null;
        MicrophoneCapture? microphone = null;
        CancellationTokenSource? cancellation = null;
        Exception? failure = null;

        lock (_gate)
        {
            if (_state is RecordingState.Recording or RecordingState.Paused or RecordingState.Stopping)
            {
                throw new InvalidOperationException("当前已经有录屏任务在运行。");
            }

            try
            {
                Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(normalized.OutputPath))!);
                writer = new AviFileWriter(
                    normalized.OutputPath,
                    normalized.Screen.Width,
                    normalized.Screen.Height,
                    normalized.FramesPerSecond,
                    normalized.SampleRate);
                _writer = writer;

                if (normalized.IncludeMicrophone)
                {
                    if (normalized.MicrophoneId is not { } microphoneId)
                    {
                        throw new InvalidOperationException("已勾选录制麦克风，但没有选择输入设备。");
                    }

                    microphone = new MicrophoneCapture(microphoneId, normalized.SampleRate);
                    microphone.AudioData += Microphone_AudioData;
                    microphone.LevelChanged += Microphone_LevelChanged;
                    _microphone = microphone;
                    microphone.Start();
                }

                cancellation = new CancellationTokenSource();
                _captureCancellation = cancellation;
                _options = normalized;
                _startedAt = DateTimeOffset.Now;
                _lastOutputPath = normalized.OutputPath;
                _lastResult = null;
                _failureMessage = string.Empty;
                Interlocked.Exchange(ref _lastVideoFrames, 0);
                Interlocked.Exchange(ref _lastAudioBytes, 0);
                _state = RecordingState.Recording;
                _captureTask = Task.Run(() => CaptureLoopAsync(cancellation.Token));
            }
            catch (Exception exception)
            {
                failure = exception;
                _state = RecordingState.Failed;
                _failureMessage = exception.Message;
            }
        }

        if (failure is not null)
        {
            DisposeResources(writer, microphone, cancellation);
            lock (_gate)
            {
                _writer = null;
                _microphone = null;
                _captureCancellation = null;
                _captureTask = null;
                _options = null;
            }

            PublishState(RecordingState.Failed, $"录屏启动失败：{failure.Message}");
            throw failure;
        }

        PublishState(RecordingState.Recording, $"正在录制：{Path.GetFileName(normalized.OutputPath)}");
    }

    public void TogglePause()
    {
        RecordingState state;
        lock (_gate)
        {
            if (_state == RecordingState.Recording)
            {
                _state = RecordingState.Paused;
            }
            else if (_state == RecordingState.Paused)
            {
                _state = RecordingState.Recording;
            }
            else
            {
                return;
            }

            state = _state;
        }

        PublishState(state, state == RecordingState.Paused
            ? "录制已暂停，屏幕和音频暂不写入文件"
            : "录制已继续");
    }

    public async Task<RecordingResult?> StopAsync()
    {
        Task? captureTask;
        bool captureFailed;
        string failureMessage;
        lock (_gate)
        {
            if (_state is RecordingState.Idle or RecordingState.Completed)
            {
                return _lastResult;
            }

            captureFailed = _state == RecordingState.Failed;
            failureMessage = _failureMessage;
            _state = RecordingState.Stopping;
            _captureCancellation?.Cancel();
            captureTask = _captureTask;
        }

        PublishState(RecordingState.Stopping, "正在收尾录屏文件…");
        if (captureTask is not null)
        {
            try
            {
                await captureTask.ConfigureAwait(false);
            }
            catch (OperationCanceledException)
            {
                // 正常停止路径。
            }
        }

        AviFileWriter? writer;
        MicrophoneCapture? microphone;
        CancellationTokenSource? cancellation;
        RecordingOptions? options;
        DateTimeOffset startedAt;
        lock (_gate)
        {
            // Detach resources before stopping WinMM.  A microphone callback may
            // need the service lock, so it must never be stopped while this lock
            // is held.
            writer = _writer;
            microphone = _microphone;
            cancellation = _captureCancellation;
            options = _options;
            startedAt = _startedAt;
            _writer = null;
            _microphone = null;
            _captureCancellation = null;
            _captureTask = null;
            _options = null;
        }

        RecordingResult? result = null;
        Exception? failure = null;
        try
        {
            if (microphone is not null)
            {
                microphone.Stop();
                microphone.AudioData -= Microphone_AudioData;
                microphone.LevelChanged -= Microphone_LevelChanged;
            }

            if (writer is not null)
            {
                writer.Complete();
                Interlocked.Exchange(ref _lastVideoFrames, writer.VideoFrames);
                Interlocked.Exchange(ref _lastAudioBytes, writer.AudioBytes);
                if (options is not null)
                {
                    result = new RecordingResult(
                        options.OutputPath,
                        DateTimeOffset.Now - startedAt,
                        writer.VideoFrames,
                        writer.AudioBytes,
                        "AVI / MJPEG 视频 + PCM 音频");
                }
            }
        }
        catch (Exception exception)
        {
            failure = exception;
        }
        finally
        {
            DisposeResources(writer, microphone, cancellation);
        }

        var finalState = failure is null && !captureFailed && result is not null
            ? RecordingState.Completed
            : RecordingState.Failed;
        var finalMessage = finalState == RecordingState.Completed
            ? $"录屏已保存：{result!.OutputPath}"
            : failure?.Message ?? (string.IsNullOrWhiteSpace(failureMessage)
                ? "录屏文件未能完成"
                : $"屏幕采集失败：{failureMessage}");

        lock (_gate)
        {
            _lastResult = result;
            _state = finalState;
            _failureMessage = finalState == RecordingState.Failed ? finalMessage : string.Empty;
        }

        PublishState(finalState, finalMessage, finalState == RecordingState.Completed ? result : null);
        return finalState == RecordingState.Completed ? result : null;
    }

    public void Dispose()
    {
        try
        {
            StopAsync().GetAwaiter().GetResult();
        }
        catch
        {
            // Application shutdown must not be blocked by a secondary cleanup
            // exception.  Capture errors were already published to the UI.
        }
    }

    private async Task CaptureLoopAsync(CancellationToken cancellationToken)
    {
        var options = _options ?? throw new InvalidOperationException("录制参数不存在。");
        var delay = TimeSpan.FromMilliseconds(1000d / options.FramesPerSecond);
        try
        {
            while (true)
            {
                await Task.Delay(delay, cancellationToken).ConfigureAwait(false);
                if (State != RecordingState.Recording)
                {
                    continue;
                }

                var jpeg = ScreenCapture.CaptureJpeg(options.Screen, options.JpegQuality);
                lock (_gate)
                {
                    if (_state == RecordingState.Recording)
                    {
                        _writer?.WriteVideoFrame(jpeg);
                    }
                }
            }
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            // 正常停止路径。
        }
        catch (Exception exception)
        {
            lock (_gate)
            {
                _failureMessage = exception.Message;
                _state = RecordingState.Failed;
            }

            PublishState(RecordingState.Failed, $"屏幕采集失败：{exception.Message}");
        }
    }

    private void Microphone_AudioData(ReadOnlyMemory<byte> data)
    {
        lock (_gate)
        {
            if (_state == RecordingState.Recording)
            {
                _writer?.WriteAudio(data.ToArray());
            }
        }
    }

    private void Microphone_LevelChanged(object? sender, MicrophoneLevelEventArgs e) =>
        LevelChanged?.Invoke(this, e);

    private void PublishState(RecordingState state, string message, RecordingResult? result = null) =>
        StateChanged?.Invoke(this, new RecordingStateChangedEventArgs(state, message, result));

    private static void DisposeResources(
        AviFileWriter? writer,
        MicrophoneCapture? microphone,
        CancellationTokenSource? cancellation)
    {
        try
        {
            microphone?.Stop();
        }
        finally
        {
            if (microphone is not null)
            {
                microphone.Dispose();
            }

            cancellation?.Dispose();
            writer?.Dispose();
        }
    }
}
