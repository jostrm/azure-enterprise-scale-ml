using Microsoft.UI.Xaml;
using System.Diagnostics;

// To learn more about WinUI, the WinUI project structure,
// and more about our project templates, see: http://aka.ms/winui-project-info.

namespace ESAIF.ConfigWizard.WinUI;

/// <summary>
/// Provides application-specific behavior to supplement the default Application class.
/// </summary>
public partial class App : MauiWinUIApplication
{
	/// <summary>
	/// Initializes the singleton application object.  This is the first line of authored code
	/// executed, and as such is the logical equivalent of main() or WinMain().
	/// </summary>
	public App()
	{
		this.InitializeComponent();
		UnhandledException += OnUnhandledException;
	}

	protected override MauiApp CreateMauiApp() => MauiProgram.CreateMauiApp();

	private static void OnUnhandledException(
		object sender,
		Microsoft.UI.Xaml.UnhandledExceptionEventArgs args)
	{
		var directory = Path.Combine(
			Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
			"ESAIF.ConfigWizard");
		try
		{
			Directory.CreateDirectory(directory);
			File.WriteAllText(
				Path.Combine(directory, "last-crash.log"),
				args.Exception.ToString());
		}
		catch (IOException exception)
		{
			Debug.WriteLine(exception);
		}
		catch (UnauthorizedAccessException exception)
		{
			Debug.WriteLine(exception);
		}
	}
}
