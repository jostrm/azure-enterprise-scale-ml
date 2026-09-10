using System.Text;

namespace ESAIF.ConfigWizard.Services;

// Keep ANSI screen/cursor controls, but never expose OSC (clipboard/links), DCS, APC, PM or SOS.
public sealed class TerminalOutputFilter
{
    private int _state;
    public void Reset() => _state = 0;

    public string Filter(string value)
    {
        var result = new StringBuilder(value.Length);
        foreach (var character in value)
        {
            switch (_state)
            {
                case 0:
                    if (character == '\x1b') _state = 1;
                    else if (character is '\x90' or '\x98' or '\x9d' or '\x9e' or '\x9f') _state = 2;
                    else result.Append(character);
                    break;
                case 1:
                    if (character is ']' or 'P' or '_' or '^' or 'X') _state = 2;
                    else
                    {
                        result.Append('\x1b').Append(character);
                        _state = 0;
                    }
                    break;
                case 2:
                    if (character is '\a' or '\x9c') _state = 0;
                    else if (character == '\x1b') _state = 3;
                    break;
                case 3:
                    if (character == '\\' || character == '\x9c') _state = 0;
                    else _state = character == '\x1b' ? 3 : 2;
                    break;
            }
        }
        return result.ToString();
    }
}
