using System.Globalization;
using ESAIF.ConfigWizard.Services;
using ESAIF.DomainLayer.Configuration;

namespace ESAIF.ConfigWizard.Controls;

public sealed class SimpleFactoryAccountConverter : IValueConverter
{
    public object Convert(object? value, Type targetType, object? parameter, CultureInfo culture) =>
        value is SimpleFactoryAzureAccount account
            ? parameter is "details" ? SimpleFactoryAccountPresentation.Details(account) : SimpleFactoryAccountPresentation.Label(account)
            : string.Empty;

    public object ConvertBack(object? value, Type targetType, object? parameter, CultureInfo culture) =>
        throw new NotSupportedException("Account labels are display-only.");
}
