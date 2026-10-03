using System.Collections.Concurrent;
using System.IO;
using System.Runtime.InteropServices;

namespace HamCheckin.Native.App.Media;

/// <summary>
/// Coordinates application-window frames, microphone PCM and the MP4 writer. The service
/// deliberately keeps all capture work off the WPF dispatcher thread.
/// </summary>
public sealed class ScreenRecordingService : IDisposable
{
    private readonly object _gate = new();
    private CancellationTokenSource? _captureCancellation;
    private Task? _captureTask;
    private Mp4FileWriter? _writer;
    private MicrophoneCapture? _microphone;
    private RecordingOptions? _options;
    private DateTimeOffset _startedAt;
    private RecordingState _state = RecordingState.Idle;
    private string _failureMessage = string.Empty;
    private RecordingResult? _lastResult;
    private long _lastVideoFrames;
    private long _lastAudioBytes;
    private string _lastOutputPath = string.Empty;
    private readonly ConcurrentQueue<byte[]> _pendingAudio = new();

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
            FramesPerSecond = Math.Clamp(options.FramesPerSecond, 1, 30)
        };

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
                while (_pendingAudio.TryDequeue(out _))
                {
                }
                _state = RecordingState.Recording;
                // The writer is created and used by this one long-running
                // worker.  Media Foundation's sink writer is not reliably
                // callable through a WPF STA-created RCW from another thread.
                _captureTask = Task.Factory.StartNew(
                    () => CaptureLoop(normalized, cancellation.Token),
                    cancellation.Token,
                    TaskCreationOptions.LongRunning,
                    TaskScheduler.Default);
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
            DisposeResources(microphone, cancellation);
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

        MicrophoneCapture? microphone;
        CancellationTokenSource? cancellation;
        RecordingOptions? options;
        DateTimeOffset startedAt;
        lock (_gate)
        {
            // Detach resources before stopping WinMM.  A microphone callback may
            // need the service lock, so it must never be stopped while this lock
            // is held.
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

        // Stop WinMM outside the service lock.  The callback also takes this
        // lock to enqueue PCM, so holding it here can deadlock shutdown.
        if (microphone is not null)
        {
            microphone.Stop();
            microphone.AudioData -= Microphone_AudioData;
            microphone.LevelChanged -= Microphone_LevelChanged;
        }

        RecordingResult? result = null;
        Exception? failure = null;
        try
        {
            if (captureFailed)
            {
                throw new InvalidOperationException(
                    string.IsNullOrWhiteSpace(failureMessage)
                        ? "屏幕采集失败。"
                        : failureMessage);
            }

            var videoFrames = Interlocked.Read(ref _lastVideoFrames);
            var audioBytes = Interlocked.Read(ref _lastAudioBytes);
            if (options is not null && videoFrames > 0)
            {
                result = new RecordingResult(
                    options.OutputPath,
                    DateTimeOffset.Now - startedAt,
                    videoFrames,
                    audioBytes,
                    "MP4 / H.264 视频 + AAC 音频");
            }
        }
        catch (Exception exception)
        {
            failure = exception;
        }
        finally
        {
            DisposeResources(microphone, cancellation);
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

    private void CaptureLoop(RecordingOptions options, CancellationToken cancellationToken)
    {
        var delay = TimeSpan.FromMilliseconds(1000d / options.FramesPerSecond);
        Mp4FileWriter? writer = null;
        var initializeResult = CoInitializeEx(nint.Zero, 0x0);
        try
        {
            writer = new Mp4FileWriter(
                options.OutputPath,
                options.Target.Width,
                options.Target.Height,
                options.FramesPerSecond,
                options.SampleRate,
                options.IncludeMicrophone);

            lock (_gate)
            {
                _writer = writer;
            }

            while (!cancellationToken.WaitHandle.WaitOne(delay))
            {
                if (State != RecordingState.Recording)
                {
                    continue;
                }

                var frame = ScreenCapture.CaptureFrame(options.Target);
                lock (_gate)
                {
                    if (_state == RecordingState.Recording)
                    {
                        writer.WriteVideoFrame(frame);
                        DrainPendingAudioLocked(writer);
                    }
                }
            }

            lock (_gate)
            {
                DrainPendingAudioLocked(writer);
                writer.Complete();
            }
        }
        catch (Exception exception)
        {
            var message = exception.Message;
            lock (_gate)
            {
                _failureMessage = message;
                _state = RecordingState.Failed;
            }

            PublishState(RecordingState.Failed, $"屏幕采集失败：{message}");
        }
        finally
        {
            if (writer is not null)
            {
                Interlocked.Exchange(ref _lastVideoFrames, writer.VideoFrames);
                Interlocked.Exchange(ref _lastAudioBytes, writer.AudioBytes);
                try
                {
                    writer.Dispose();
                }
                catch (Exception exception)
                {
                    lock (_gate)
                    {
                        if (_state is not RecordingState.Failed)
                        {
                            _failureMessage = exception.Message;
                            _state = RecordingState.Failed;
                        }
                    }
                }

                lock (_gate)
                {
                    if (ReferenceEquals(_writer, writer))
                    {
                        _writer = null;
                    }
                }
            }

            if (initializeResult >= 0)
            {
                CoUninitialize();
            }
        }
    }

    private void Microphone_AudioData(ReadOnlyMemory<byte> data)
    {
        lock (_gate)
        {
            if (_state == RecordingState.Recording)
            {
                _pendingAudio.Enqueue(data.ToArray());
            }
        }
    }

    private void DrainPendingAudioLocked(Mp4FileWriter writer)
    {
        while (_pendingAudio.TryDequeue(out var pcm))
        {
            writer.WriteAudio(pcm);
        }
    }

    private void Microphone_LevelChanged(object? sender, MicrophoneLevelEventArgs e) =>
        LevelChanged?.Invoke(this, e);

    private void PublishState(RecordingState state, string message, RecordingResult? result = null) =>
        StateChanged?.Invoke(this, new RecordingStateChangedEventArgs(state, message, result));

    private static void DisposeResources(
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
        }
    }

    [DllImport("ole32.dll")]
    private static extern int CoInitializeEx(nint reserved, uint coInit);

    [DllImport("ole32.dll")]
    private static extern void CoUninitialize();
}
