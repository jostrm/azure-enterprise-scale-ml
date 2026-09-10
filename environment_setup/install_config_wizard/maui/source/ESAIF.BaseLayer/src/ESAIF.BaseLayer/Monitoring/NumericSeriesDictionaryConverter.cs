using System.Globalization;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace ESAIF.BaseLayer.Monitoring;

internal sealed class NumericSeriesDictionaryConverter
    : JsonConverter<IReadOnlyDictionary<string, IReadOnlyList<double>>>
{
    public override IReadOnlyDictionary<string, IReadOnlyList<double>> Read(
        ref Utf8JsonReader reader,
        Type typeToConvert,
        JsonSerializerOptions options)
    {
        if (reader.TokenType == JsonTokenType.Null)
        {
            return new Dictionary<string, IReadOnlyList<double>>(StringComparer.Ordinal);
        }

        if (reader.TokenType != JsonTokenType.StartObject)
        {
            throw new JsonException("Chart series must be a JSON object.");
        }

        var result = new Dictionary<string, IReadOnlyList<double>>(StringComparer.Ordinal);
        while (reader.Read() && reader.TokenType != JsonTokenType.EndObject)
        {
            if (reader.TokenType != JsonTokenType.PropertyName)
            {
                throw new JsonException("Chart series contains an invalid property.");
            }

            var name = reader.GetString() ?? string.Empty;
            reader.Read();
            result[name] = ReadValues(ref reader);
        }

        return result;
    }

    public override void Write(
        Utf8JsonWriter writer,
        IReadOnlyDictionary<string, IReadOnlyList<double>> value,
        JsonSerializerOptions options)
    {
        writer.WriteStartObject();
        foreach (var (name, values) in value)
        {
            writer.WritePropertyName(name);
            writer.WriteStartArray();
            foreach (var item in values)
            {
                writer.WriteNumberValue(item);
            }

            writer.WriteEndArray();
        }

        writer.WriteEndObject();
    }

    private static IReadOnlyList<double> ReadValues(ref Utf8JsonReader reader)
    {
        if (reader.TokenType == JsonTokenType.Null)
        {
            return [];
        }

        if (reader.TokenType != JsonTokenType.StartArray)
        {
            throw new JsonException("Each chart series must be a JSON array.");
        }

        var values = new List<double>();
        while (reader.Read() && reader.TokenType != JsonTokenType.EndArray)
        {
            if (reader.TokenType == JsonTokenType.Number && reader.TryGetDouble(out var number))
            {
                values.Add(number);
                continue;
            }

            if (reader.TokenType == JsonTokenType.String &&
                double.TryParse(
                    reader.GetString(),
                    NumberStyles.Float,
                    CultureInfo.InvariantCulture,
                    out number))
            {
                values.Add(number);
                continue;
            }

            throw new JsonException("Chart series values must be numbers.");
        }

        return values;
    }
}
