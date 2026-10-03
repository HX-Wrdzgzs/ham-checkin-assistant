using System.IO;
using System.Runtime.InteropServices;

namespace HamCheckin.Native.App.Media;

/// <summary>
/// Windows-native MP4 writer backed by Media Foundation's H.264 and AAC
/// encoders. It accepts RGB32 video frames and mono 16-bit PCM microphone
/// samples, so no ffmpeg, Python, Qt or external codec is required.
/// </summary>
internal sealed class Mp4FileWriter : IDisposable
{
    private const uint Progressive = 2;
    private const long TicksPerSecond = 10_000_000;
    private readonly object _gate = new();
    private readonly int _width;
    private readonly int _height;
    private readonly int _framesPerSecond;
    private readonly int _sampleRate;
    private readonly int _channels;
    private readonly uint _videoStream;
    private readonly uint? _audioStream;
    private readonly IDisposable _mediaFoundationLifetime;
    private IMFSinkWriter? _sinkWriter;
    private long _videoFrames;
    private long _audioBytes;
    private long _audioSamples;
    private bool _completed;

    public Mp4FileWriter(
        string outputPath,
        int width,
        int height,
        int framesPerSecond,
        int sampleRate,
        bool includeAudio,
        int channels = 1)
    {
        if (width <= 0 || height <= 0)
        {
            throw new ArgumentOutOfRangeException(nameof(width), "录制尺寸无效。");
        }

        if (string.IsNullOrWhiteSpace(outputPath) ||
            !outputPath.EndsWith(".mp4", StringComparison.OrdinalIgnoreCase))
        {
            throw new ArgumentException("录屏输出文件必须使用 .mp4 扩展名。", nameof(outputPath));
        }

        _width = width;
        _height = height;
        _framesPerSecond = Math.Clamp(framesPerSecond, 1, 30);
        _sampleRate = sampleRate is 44_100 or 48_000 ? sampleRate : 44_100;
        _channels = channels is 1 or 2 ? channels : 1;
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(outputPath))!);

        _mediaFoundationLifetime = MediaFoundationRuntime.Enter();
        try
        {
            MediaFoundationNative.ThrowIfFailed(
                MediaFoundationNative.MFCreateSinkWriterFromURL(
                    outputPath,
                    nint.Zero,
                    nint.Zero,
                    out var sinkWriter),
                "创建 MP4 编码器失败。");
            _sinkWriter = sinkWriter;

            _videoStream = AddVideoStream(sinkWriter);
            if (includeAudio)
            {
                _audioStream = AddAudioStream(sinkWriter);
            }

            MediaFoundationNative.ThrowIfFailed(
                sinkWriter.BeginWriting(),
                "启动 MP4 写入失败。");
        }
        catch
        {
            Dispose();
            throw;
        }
    }

    public long VideoFrames => Interlocked.Read(ref _videoFrames);
    public long AudioBytes => Interlocked.Read(ref _audioBytes);

    public void WriteVideoFrame(byte[] rgb32)
    {
        ArgumentNullException.ThrowIfNull(rgb32);
        var expectedLength = checked(_width * _height * 4);
        if (rgb32.Length < expectedLength)
        {
            throw new ArgumentException("录屏帧尺寸与 MP4 编码器不一致。", nameof(rgb32));
        }

        lock (_gate)
        {
            EnsureOpen();
            var timestamp = _videoFrames * TicksPerSecond / _framesPerSecond;
            var duration = TicksPerSecond / _framesPerSecond;
            using var sample = CreateSample(rgb32, timestamp, duration);
            MediaFoundationNative.ThrowIfFailed(
                _sinkWriter!.WriteSample(_videoStream, sample.Sample),
                "写入 MP4 视频帧失败。");
            _videoFrames++;
        }
    }

    public void WriteAudio(byte[] pcm)
    {
        ArgumentNullException.ThrowIfNull(pcm);
        var blockAlignment = checked(_channels * 2);
        if (pcm.Length == 0)
        {
            return;
        }

        var usableLength = pcm.Length - pcm.Length % blockAlignment;
        if (usableLength == 0)
        {
            return;
        }

        lock (_gate)
        {
            EnsureOpen();
            var sampleCount = usableLength / blockAlignment;
            var timestamp = _audioSamples * TicksPerSecond / _sampleRate;
            var duration = sampleCount * TicksPerSecond / _sampleRate;
            using var sample = CreateSample(pcm, usableLength, timestamp, duration);
            MediaFoundationNative.ThrowIfFailed(
                _sinkWriter!.WriteSample(_audioStream!.Value, sample.Sample),
                "写入 MP4 音频帧失败。");
            _audioSamples += sampleCount;
            _audioBytes += usableLength;
        }
    }

    public void Complete()
    {
        lock (_gate)
        {
            if (_completed)
            {
                return;
            }

            EnsureOpen();
            MediaFoundationNative.ThrowIfFailed(
                _sinkWriter!.Finalize(),
                "完成 MP4 文件失败。");
            _completed = true;
        }
    }

    public void Dispose()
    {
        try
        {
            lock (_gate)
            {
                if (!_completed && _sinkWriter is not null)
                {
                    try
                    {
                        _sinkWriter.Finalize();
                    }
                    catch
                    {
                        // Preserve the original capture/encoding error while
                        // still releasing Media Foundation resources.
                    }

                    _completed = true;
                }

                MediaFoundationNative.Release(_sinkWriter);
                _sinkWriter = null;
            }
        }
        finally
        {
            _mediaFoundationLifetime.Dispose();
        }
    }

    private uint AddVideoStream(IMFSinkWriter sinkWriter)
    {
        IMFMediaType? outputType = null;
        IMFMediaType? inputType = null;
        try
        {
            outputType = CreateMediaType(
                MediaFoundationNative.MfMediaTypeVideo,
                MediaFoundationNative.MfVideoFormatH264);
            SetUInt32(outputType, MediaFoundationNative.MfMtAvgBitrate, CalculateVideoBitrate());
            SetRatio(outputType, MediaFoundationNative.MfMtFrameSize, _width, _height);
            SetRatio(outputType, MediaFoundationNative.MfMtFrameRate, _framesPerSecond, 1);
            SetRatio(outputType, MediaFoundationNative.MfMtPixelAspectRatio, 1, 1);
            SetUInt32(outputType, MediaFoundationNative.MfMtInterlaceMode, Progressive);

            MediaFoundationNative.ThrowIfFailed(
                sinkWriter.AddStream(outputType, out var streamIndex),
                "添加 MP4 视频流失败。");

            inputType = CreateMediaType(
                MediaFoundationNative.MfMediaTypeVideo,
                MediaFoundationNative.MfVideoFormatRgb32);
            SetRatio(inputType, MediaFoundationNative.MfMtFrameSize, _width, _height);
            SetRatio(inputType, MediaFoundationNative.MfMtFrameRate, _framesPerSecond, 1);
            SetRatio(inputType, MediaFoundationNative.MfMtPixelAspectRatio, 1, 1);
            SetUInt32(inputType, MediaFoundationNative.MfMtInterlaceMode, Progressive);
            MediaFoundationNative.ThrowIfFailed(
                sinkWriter.SetInputMediaType(streamIndex, inputType, nint.Zero),
                "设置 MP4 视频输入格式失败。");
            return streamIndex;
        }
        finally
        {
            MediaFoundationNative.Release(inputType);
            MediaFoundationNative.Release(outputType);
        }
    }

    private uint AddAudioStream(IMFSinkWriter sinkWriter)
    {
        IMFMediaType? outputType = null;
        IMFMediaType? inputType = null;
        try
        {
            outputType = CreateMediaType(
                MediaFoundationNative.MfMediaTypeAudio,
                MediaFoundationNative.MfAudioFormatAac);
            SetUInt32(outputType, MediaFoundationNative.MfMtAudioNumChannels, (uint)_channels);
            SetUInt32(outputType, MediaFoundationNative.MfMtAudioSamplesPerSecond, (uint)_sampleRate);
            SetUInt32(outputType, MediaFoundationNative.MfMtAudioBitsPerSample, 16);
            SetUInt32(outputType, MediaFoundationNative.MfMtAudioAvgBytesPerSecond, 12_000);

            MediaFoundationNative.ThrowIfFailed(
                sinkWriter.AddStream(outputType, out var streamIndex),
                "添加 MP4 音频流失败。");

            inputType = CreateMediaType(
                MediaFoundationNative.MfMediaTypeAudio,
                MediaFoundationNative.MfAudioFormatPcm);
            SetUInt32(inputType, MediaFoundationNative.MfMtAudioNumChannels, (uint)_channels);
            SetUInt32(inputType, MediaFoundationNative.MfMtAudioSamplesPerSecond, (uint)_sampleRate);
            SetUInt32(inputType, MediaFoundationNative.MfMtAudioBitsPerSample, 16);
            SetUInt32(inputType, MediaFoundationNative.MfMtAudioBlockAlignment, (uint)(_channels * 2));
            SetUInt32(inputType, MediaFoundationNative.MfMtAudioAvgBytesPerSecond, (uint)(_sampleRate * _channels * 2));
            SetUInt32(inputType, MediaFoundationNative.MfMtAllSamplesIndependent, 1);
            SetUInt32(inputType, MediaFoundationNative.MfMtFixedSizeSamples, 1);
            MediaFoundationNative.ThrowIfFailed(
                sinkWriter.SetInputMediaType(streamIndex, inputType, nint.Zero),
                "设置 MP4 音频输入格式失败。");
            return streamIndex;
        }
        finally
        {
            MediaFoundationNative.Release(inputType);
            MediaFoundationNative.Release(outputType);
        }
    }

    private SampleHandle CreateSample(byte[] bytes, long timestamp, long duration) =>
        CreateSample(bytes, bytes.Length, timestamp, duration);

    private SampleHandle CreateSample(byte[] bytes, int length, long timestamp, long duration)
    {
        IMFMediaBuffer? buffer = null;
        IMFSample? sample = null;
        try
        {
            MediaFoundationNative.ThrowIfFailed(
                MediaFoundationNative.MFCreateMemoryBuffer((uint)length, out buffer),
                "创建 MP4 样本缓冲区失败。");
            MediaFoundationNative.ThrowIfFailed(
                buffer.Lock(out var destination, out _, out _),
                "锁定 MP4 样本缓冲区失败。");
            try
            {
                Marshal.Copy(bytes, 0, destination, length);
            }
            finally
            {
                MediaFoundationNative.ThrowIfFailed(buffer.Unlock(), "解锁 MP4 样本缓冲区失败。");
            }

            MediaFoundationNative.ThrowIfFailed(buffer.SetCurrentLength((uint)length), "设置 MP4 样本长度失败。");
            MediaFoundationNative.ThrowIfFailed(
                MediaFoundationNative.MFCreateSample(out sample),
                "创建 MP4 样本失败。");
            MediaFoundationNative.ThrowIfFailed(sample.AddBuffer(buffer), "加入 MP4 样本缓冲区失败。");
            MediaFoundationNative.ThrowIfFailed(sample.SetSampleTime(timestamp), "设置 MP4 样本时间失败。");
            MediaFoundationNative.ThrowIfFailed(sample.SetSampleDuration(duration), "设置 MP4 样本时长失败。");
            return new SampleHandle(sample);
        }
        catch
        {
            MediaFoundationNative.Release(sample);
            throw;
        }
        finally
        {
            MediaFoundationNative.Release(buffer);
        }
    }

    private void EnsureOpen()
    {
        if (_sinkWriter is null || _completed)
        {
            throw new ObjectDisposedException(nameof(Mp4FileWriter));
        }
    }

    private uint CalculateVideoBitrate()
    {
        var estimate = (long)_width * _height * _framesPerSecond / 2;
        return (uint)Math.Clamp(estimate, 1_000_000L, 12_000_000L);
    }

    private static IMFMediaType CreateMediaType(Guid majorType, Guid subtype)
    {
        MediaFoundationNative.ThrowIfFailed(
            MediaFoundationNative.MFCreateMediaType(out var mediaType),
            "创建 Media Foundation 媒体类型失败。");
        try
        {
            SetGuid(mediaType, MediaFoundationNative.MfMtMajorType, majorType);
            SetGuid(mediaType, MediaFoundationNative.MfMtSubtype, subtype);
            return mediaType;
        }
        catch
        {
            MediaFoundationNative.Release(mediaType);
            throw;
        }
    }

    private static void SetGuid(IMFMediaType attributes, Guid key, Guid value) =>
        MediaFoundationNative.ThrowIfFailed(attributes.SetGUID(ref key, ref value), "设置媒体类型 GUID 失败。");

    private static void SetUInt32(IMFMediaType attributes, Guid key, uint value) =>
        MediaFoundationNative.ThrowIfFailed(attributes.SetUINT32(ref key, value), "设置媒体类型数值失败。");

    private static void SetRatio(IMFMediaType attributes, Guid key, int numerator, int denominator)
    {
        var packed = ((ulong)(uint)numerator << 32) | (uint)denominator;
        MediaFoundationNative.ThrowIfFailed(attributes.SetUINT64(ref key, packed), "设置媒体类型比例失败。");
    }

    private sealed class SampleHandle(IMFSample sample) : IDisposable
    {
        public IMFSample Sample { get; } = sample;
        public void Dispose() => MediaFoundationNative.Release(Sample);
    }

    private sealed class MediaFoundationRuntime : IDisposable
    {
        private static readonly object Gate = new();
        private static int _activeUsers;
        private bool _released;

        public static MediaFoundationRuntime Enter()
        {
            lock (Gate)
            {
                if (_activeUsers == 0)
                {
                    MediaFoundationNative.ThrowIfFailed(
                        MediaFoundationNative.MFStartup(MediaFoundationNative.MfVersion, 0),
                        "启动 Windows Media Foundation 失败。");
                }

                _activeUsers++;
                return new MediaFoundationRuntime();
            }
        }

        public void Dispose()
        {
            lock (Gate)
            {
                if (_released)
                {
                    return;
                }

                _released = true;
                _activeUsers--;
                if (_activeUsers == 0)
                {
                    MediaFoundationNative.ThrowIfFailed(
                        MediaFoundationNative.MFShutdown(),
                        "关闭 Windows Media Foundation 失败。");
                }
            }
        }
    }
}
