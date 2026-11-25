using HamCheckin.Native.Core;
using HamCheckin.Native.Core.Memory;

namespace HamCheckin.Native.App.ViewModels;

/// <summary>
/// 一条可点击的呼号记忆提示。只负责显示内容；应用与撤销由 MainViewModel 执行，
/// 因此 chip 本身不持有输入框或存储引用。
/// </summary>
public sealed class CallsignHintChip(CallsignFieldHint hint, bool replacesCurrentValue)
{
    public FieldKind Field => hint.Field;
    public string Value => hint.Value;
    public int UseCount => hint.UseCount;
    public string FieldLabel => Label(hint.Field);

    public string DisplayText => replacesCurrentValue
        ? $"{FieldLabel} 改为 {hint.Value} · {hint.UseCount} 次"
        : $"{FieldLabel} {hint.Value} · {hint.UseCount} 次";

    public string AutomationName => replacesCurrentValue
        ? $"呼号记忆 {FieldLabel} {hint.Value}，历史 {hint.UseCount} 次；点击覆盖当前值"
        : $"呼号记忆 {FieldLabel} {hint.Value}，历史 {hint.UseCount} 次；点击填入";

    private static string Label(FieldKind field) => field switch
    {
        FieldKind.Qth => "QTH",
        FieldKind.Device => "设备",
        FieldKind.Antenna => "天线",
        FieldKind.Power => "功率",
        _ => throw new ArgumentOutOfRangeException(nameof(field), field, "呼号记忆只覆盖 QTH/设备/天线/功率")
    };
}
