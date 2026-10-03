using System.Runtime.InteropServices;

namespace HamCheckin.Native.App.Media;

internal static class MediaFoundationNative
{
    internal const uint MfVersion = 0x0002_0070;
    internal const int SOk = 0;

    internal static readonly Guid MfMtMajorType = new("48eba18e-f8c9-4687-bf11-0a74c9f96a8f");
    internal static readonly Guid MfMtSubtype = new("f7e34c9a-42e8-4714-b74b-cb29d72c35e5");
    internal static readonly Guid MfMtAvgBitrate = new("20332624-fb0d-4d9e-bd0d-cbf6786c102e");
    internal static readonly Guid MfMtFrameSize = new("1652c33d-d6b2-4012-b834-72030849a37d");
    internal static readonly Guid MfMtFrameRate = new("c459a2e8-3d2c-4e44-b132-fee5156c7bb0");
    internal static readonly Guid MfMtPixelAspectRatio = new("c6376a1e-8d0a-4027-be45-6d9a0ad39bb6");
    internal static readonly Guid MfMtInterlaceMode = new("e2724bb8-e676-4806-b4b2-a8d6efb44ccd");
    internal static readonly Guid MfMtAllSamplesIndependent = new("c9173739-5e56-461c-b713-46fb995cb95f");
    internal static readonly Guid MfMtFixedSizeSamples = new("b8ebefaf-b718-4e04-b0a9-116775e3321b");
    internal static readonly Guid MfMtAudioNumChannels = new("37e48bf5-645e-4c5b-89de-ada9e29b696a");
    internal static readonly Guid MfMtAudioSamplesPerSecond = new("5faeeae7-0290-4c31-9e8a-c534f68d9dba");
    internal static readonly Guid MfMtAudioAvgBytesPerSecond = new("1aab75c8-cfef-451c-ab95-ac034b8e1731");
    internal static readonly Guid MfMtAudioBlockAlignment = new("322de230-9eeb-43bd-ab7a-ff412251541d");
    internal static readonly Guid MfMtAudioBitsPerSample = new("f2deb57f-40fa-4764-aa33-ed4f2d1ff669");

    internal static readonly Guid MfMediaTypeVideo = new("73646976-0000-0010-8000-00aa00389b71");
    internal static readonly Guid MfMediaTypeAudio = new("73647561-0000-0010-8000-00aa00389b71");
    internal static readonly Guid MfVideoFormatRgb32 = new("00000016-0000-0010-8000-00aa00389b71");
    internal static readonly Guid MfVideoFormatH264 = new("34363248-0000-0010-8000-00aa00389b71");
    internal static readonly Guid MfAudioFormatPcm = new("00000001-0000-0010-8000-00aa00389b71");
    internal static readonly Guid MfAudioFormatAac = new("00001610-0000-0010-8000-00aa00389b71");

    [DllImport("mfplat.dll", ExactSpelling = true)]
    internal static extern int MFStartup(uint version, uint flags);

    [DllImport("mfplat.dll", ExactSpelling = true)]
    internal static extern int MFShutdown();

    [DllImport("mfplat.dll", ExactSpelling = true)]
    internal static extern int MFCreateMediaType(out IMFMediaType mediaType);

    [DllImport("mfplat.dll", ExactSpelling = true)]
    internal static extern int MFCreateMemoryBuffer(uint maxLength, out IMFMediaBuffer buffer);

    [DllImport("mfplat.dll", ExactSpelling = true)]
    internal static extern int MFCreateSample(out IMFSample sample);

    [DllImport("mfreadwrite.dll", ExactSpelling = true, CharSet = CharSet.Unicode)]
    internal static extern int MFCreateSinkWriterFromURL(
        string outputUrl,
        nint byteStream,
        nint attributes,
        out IMFSinkWriter sinkWriter);

    internal static void ThrowIfFailed(int hResult, string operation)
    {
        if (hResult < 0)
        {
            throw new COMException(operation, hResult);
        }
    }

    internal static void Release(object? value)
    {
        if (value is not null && Marshal.IsComObject(value))
        {
            Marshal.FinalReleaseComObject(value);
        }
    }
}

[ComImport]
[Guid("2cd2d921-c447-44a7-a13c-4adabfc247e3")]
[InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
internal interface IMFAttributes
{
    int GetItem(ref Guid key, nint value);
    int GetItemType(ref Guid key, out uint type);
    int CompareItem(ref Guid key, nint value, out int result);
    int Compare(IMFAttributes? theirs, uint matchType, out int result);
    int GetUINT32(ref Guid key, out uint value);
    int GetUINT64(ref Guid key, out ulong value);
    int GetDouble(ref Guid key, out double value);
    int GetGUID(ref Guid key, out Guid value);
    int GetStringLength(ref Guid key, out uint length);
    int GetString(ref Guid key, nint value, uint bufferSize, out uint length);
    int GetAllocatedString(ref Guid key, out nint value, out uint length);
    int GetBlobSize(ref Guid key, out uint size);
    int GetBlob(ref Guid key, nint buffer, uint bufferSize, out uint size);
    int GetAllocatedBlob(ref Guid key, out nint buffer, out uint size);
    int GetUnknown(ref Guid key, ref Guid interfaceId, out nint value);
    int SetItem(ref Guid key, nint value);
    int DeleteItem(ref Guid key);
    int DeleteAllItems();
    int SetUINT32(ref Guid key, uint value);
    int SetUINT64(ref Guid key, ulong value);
    int SetDouble(ref Guid key, double value);
    int SetGUID(ref Guid key, ref Guid value);
    int SetString(ref Guid key, [MarshalAs(UnmanagedType.LPWStr)] string value);
    int SetBlob(ref Guid key, nint buffer, uint bufferSize);
    int SetUnknown(ref Guid key, nint unknown);
    int LockStore();
    int UnlockStore();
    int GetCount(out uint count);
    int GetItemByIndex(uint index, out Guid key, nint value);
    int CopyAllItems(IMFAttributes destination);
}

[ComImport]
[Guid("44ae0fa8-ea31-4109-8d2e-4cae4997c555")]
[InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
internal interface IMFMediaType
{
    int GetItem(ref Guid key, nint value);
    int GetItemType(ref Guid key, out uint type);
    int CompareItem(ref Guid key, nint value, out int result);
    int Compare(IMFAttributes? theirs, uint matchType, out int result);
    int GetUINT32(ref Guid key, out uint value);
    int GetUINT64(ref Guid key, out ulong value);
    int GetDouble(ref Guid key, out double value);
    int GetGUID(ref Guid key, out Guid value);
    int GetStringLength(ref Guid key, out uint length);
    int GetString(ref Guid key, nint value, uint bufferSize, out uint length);
    int GetAllocatedString(ref Guid key, out nint value, out uint length);
    int GetBlobSize(ref Guid key, out uint size);
    int GetBlob(ref Guid key, nint buffer, uint bufferSize, out uint size);
    int GetAllocatedBlob(ref Guid key, out nint buffer, out uint size);
    int GetUnknown(ref Guid key, ref Guid interfaceId, out nint value);
    int SetItem(ref Guid key, nint value);
    int DeleteItem(ref Guid key);
    int DeleteAllItems();
    int SetUINT32(ref Guid key, uint value);
    int SetUINT64(ref Guid key, ulong value);
    int SetDouble(ref Guid key, double value);
    int SetGUID(ref Guid key, ref Guid value);
    int SetString(ref Guid key, [MarshalAs(UnmanagedType.LPWStr)] string value);
    int SetBlob(ref Guid key, nint buffer, uint bufferSize);
    int SetUnknown(ref Guid key, nint unknown);
    int LockStore();
    int UnlockStore();
    int GetCount(out uint count);
    int GetItemByIndex(uint index, out Guid key, nint value);
    int CopyAllItems(IMFAttributes destination);
    int GetMajorType(out Guid majorType);
    int IsCompressedFormat(out int compressed);
    int IsEqual(IMFMediaType mediaType, out uint flags);
    int GetRepresentation(ref Guid representation, out nint value);
    int FreeRepresentation(ref Guid representation, nint value);
}

[ComImport]
[Guid("045fa593-8799-42b8-bc8d-8968c6453507")]
[InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
internal interface IMFMediaBuffer
{
    int Lock(out nint buffer, out uint maxLength, out uint currentLength);
    int Unlock();
    int GetCurrentLength(out uint currentLength);
    int SetCurrentLength(uint currentLength);
    int GetMaxLength(out uint maxLength);
}

[ComImport]
[Guid("c40a00f2-b93a-4d80-ae8c-5a1c634f58e4")]
[InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
internal interface IMFSample
{
    int GetItem(ref Guid key, nint value);
    int GetItemType(ref Guid key, out uint type);
    int CompareItem(ref Guid key, nint value, out int result);
    int Compare(IMFAttributes? theirs, uint matchType, out int result);
    int GetUINT32(ref Guid key, out uint value);
    int GetUINT64(ref Guid key, out ulong value);
    int GetDouble(ref Guid key, out double value);
    int GetGUID(ref Guid key, out Guid value);
    int GetStringLength(ref Guid key, out uint length);
    int GetString(ref Guid key, nint value, uint bufferSize, out uint length);
    int GetAllocatedString(ref Guid key, out nint value, out uint length);
    int GetBlobSize(ref Guid key, out uint size);
    int GetBlob(ref Guid key, nint buffer, uint bufferSize, out uint size);
    int GetAllocatedBlob(ref Guid key, out nint buffer, out uint size);
    int GetUnknown(ref Guid key, ref Guid interfaceId, out nint value);
    int SetItem(ref Guid key, nint value);
    int DeleteItem(ref Guid key);
    int DeleteAllItems();
    int SetUINT32(ref Guid key, uint value);
    int SetUINT64(ref Guid key, ulong value);
    int SetDouble(ref Guid key, double value);
    int SetGUID(ref Guid key, ref Guid value);
    int SetString(ref Guid key, [MarshalAs(UnmanagedType.LPWStr)] string value);
    int SetBlob(ref Guid key, nint buffer, uint bufferSize);
    int SetUnknown(ref Guid key, nint unknown);
    int LockStore();
    int UnlockStore();
    int GetCount(out uint count);
    int GetItemByIndex(uint index, out Guid key, nint value);
    int CopyAllItems(IMFAttributes destination);
    int GetSampleFlags(out uint flags);
    int SetSampleFlags(uint flags);
    int GetSampleTime(out long time);
    int SetSampleTime(long time);
    int GetSampleDuration(out long duration);
    int SetSampleDuration(long duration);
    int GetBufferCount(out uint count);
    int GetBufferByIndex(uint index, out IMFMediaBuffer buffer);
    int ConvertToContiguousBuffer(out IMFMediaBuffer buffer);
    int AddBuffer(IMFMediaBuffer buffer);
    int RemoveBufferByIndex(uint index);
    int RemoveAllBuffers();
    int GetTotalLength(out uint length);
    int CopyToBuffer(IMFMediaBuffer buffer);
}

[ComImport]
[Guid("3137f1cd-fe5e-4805-a5d8-fb477448cb3d")]
[InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
internal interface IMFSinkWriter
{
    int AddStream(IMFMediaType targetMediaType, out uint streamIndex);
    int SetInputMediaType(uint streamIndex, IMFMediaType inputMediaType, nint encodingParameters);
    int BeginWriting();
    int WriteSample(uint streamIndex, IMFSample sample);
    int SendStreamTick(uint streamIndex, long timestamp);
    int PlaceMarker(uint streamIndex, nint context);
    int NotifyEndOfSegment(uint streamIndex);
    int Flush(uint streamIndex);
    int Finalize();
    int GetServiceForStream(uint streamIndex, ref Guid service, ref Guid interfaceId, out nint value);
    int GetStatistics(uint streamIndex, nint statistics);
}
