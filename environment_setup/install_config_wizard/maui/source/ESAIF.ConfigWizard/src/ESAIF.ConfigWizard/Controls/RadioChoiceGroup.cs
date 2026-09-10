using System.ComponentModel;

namespace ESAIF.ConfigWizard.Controls;

internal sealed class RadioChoiceGroup<T> where T : class, INotifyPropertyChanged
{
    private readonly ContentView _owner;
    private readonly (RadioButton Button, Func<T, bool> Selected, Action<T> Select)[] _choices;
    private T? _model;
    private bool _loaded;
    private bool _rendering;
    private bool _queued;

    public RadioChoiceGroup(ContentView owner,
        params (RadioButton Button, Func<T, bool> Selected, Action<T> Select)[] choices)
    {
        _owner = owner;
        _choices = choices;
        var group = Guid.NewGuid().ToString("N");
        foreach (var choice in choices)
        {
            choice.Button.GroupName = group;
            choice.Button.CheckedChanged += (_, e) =>
            {
                if (!_rendering && e.Value && _model is { } model && !choice.Selected(model))
                {
                    choice.Select(model);
                    QueueRender();
                }
            };
        }
        owner.BindingContextChanged += (_, _) => BindModel();
        owner.Loaded += (_, _) => { _loaded = true; BindModel(); };
        owner.Unloaded += (_, _) =>
        {
            _loaded = false;
            if (_model is not null)
            {
                _model.PropertyChanged -= OnModelChanged;
            }
            _model = null;
        };
    }

    private void BindModel()
    {
        if (_model is not null)
        {
            _model.PropertyChanged -= OnModelChanged;
        }
        _model = _owner.BindingContext as T;
        if (_loaded && _model is not null)
        {
            _model.PropertyChanged += OnModelChanged;
        }
        QueueRender();
    }

    private void OnModelChanged(object? sender, PropertyChangedEventArgs e) => QueueRender();

    private void QueueRender()
    {
        if (_queued)
        {
            return;
        }
        _queued = true;
        // Do not write IsChecked back inside WinUI's Checked/Unchecked callback.
        // MAUI's native handler otherwise repeatedly restores a competing binding value.
        _owner.Dispatcher.Dispatch(() =>
        {
            _queued = false;
            if (!_loaded)
            {
                return;
            }
            _rendering = true;
            try
            {
                foreach (var choice in _choices.Where(choice => _model is null || !choice.Selected(_model)))
                {
                    choice.Button.IsChecked = false;
                }
                foreach (var choice in _choices.Where(choice => _model is not null && choice.Selected(_model)))
                {
                    choice.Button.IsChecked = true;
                }
            }
            finally
            {
                _rendering = false;
            }
        });
    }
}
