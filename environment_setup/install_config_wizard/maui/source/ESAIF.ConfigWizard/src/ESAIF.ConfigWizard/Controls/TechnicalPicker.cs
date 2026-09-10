using System.Collections;
using System.Collections.Specialized;
using System.ComponentModel;
using ESAIF.ConfigWizard.Pages;
using ESAIF.ConfigWizard.Services;

namespace ESAIF.ConfigWizard.Controls;

/// <summary>Display-only choice wrappers preserve the identity of the selected source item.</summary>
public sealed class TechnicalPicker : Grid
{
    public static readonly BindableProperty ItemsSourceProperty = BindableProperty.Create(
        nameof(ItemsSource), typeof(IList), typeof(TechnicalPicker), null, propertyChanged: ItemsChanged);
    public static readonly BindableProperty SelectedItemProperty = BindableProperty.Create(
        nameof(SelectedItem), typeof(object), typeof(TechnicalPicker), null, BindingMode.TwoWay, propertyChanged: SelectionChanged);
    public static readonly BindableProperty TitleProperty = BindableProperty.Create(
        nameof(Title), typeof(string), typeof(TechnicalPicker), string.Empty, propertyChanged: AppearanceChanged);
    public static readonly BindableProperty FontSizeProperty = BindableProperty.Create(
        nameof(FontSize), typeof(double), typeof(TechnicalPicker), 14d, propertyChanged: AppearanceChanged);
    public static readonly BindableProperty HorizontalTextAlignmentProperty = BindableProperty.Create(
        nameof(HorizontalTextAlignment), typeof(TextAlignment), typeof(TechnicalPicker), TextAlignment.Start, propertyChanged: AppearanceChanged);
    public static readonly BindableProperty TextColorProperty = BindableProperty.Create(
        nameof(TextColor), typeof(Color), typeof(TechnicalPicker), null, propertyChanged: AppearanceChanged);
    public static readonly BindableProperty TitleColorProperty = BindableProperty.Create(
        nameof(TitleColor), typeof(Color), typeof(TechnicalPicker), null, propertyChanged: AppearanceChanged);

    private readonly Picker _picker = new() { ItemDisplayBinding = new Binding(nameof(Choice.Display)) };
    private readonly Button _details = new() { Text = "Details", FontSize = 12, Padding = new Thickness(8, 2), IsVisible = false };
    private List<Choice> _choices = [];
    private bool _syncing;
    private bool _showing;
    private INotifyCollectionChanged? _observed;
    private readonly List<INotifyPropertyChanged> _observedItems = [];
    private readonly ValueReader _reader = new();
    private BindingBase? _itemDisplayBinding;
    private BindingBase? _itemDetailsBinding;
    private CancellationTokenSource? _disclosure;
    public event EventHandler? SelectedIndexChanged;
    public IList? ItemsSource { get => (IList?)GetValue(ItemsSourceProperty); set => SetValue(ItemsSourceProperty, value); }
    public object? SelectedItem { get => GetValue(SelectedItemProperty); set => SetValue(SelectedItemProperty, value); }
    // Like Picker.ItemDisplayBinding, these are CLR properties: XAML must pass the
    // binding object, not bind a BindableProperty against the page's view model.
    public BindingBase? ItemDisplayBinding
    {
        get => _itemDisplayBinding;
        set
        {
            if (_itemDisplayBinding == value) return;
            _itemDisplayBinding = value;
            BuildChoices();
        }
    }
    public BindingBase? ItemDetailsBinding
    {
        get => _itemDetailsBinding;
        set
        {
            if (_itemDetailsBinding == value) return;
            _itemDetailsBinding = value;
            BuildChoices();
        }
    }
    public string Title { get => (string)GetValue(TitleProperty); set => SetValue(TitleProperty, value); }
    public double FontSize { get => (double)GetValue(FontSizeProperty); set => SetValue(FontSizeProperty, value); }
    public TextAlignment HorizontalTextAlignment { get => (TextAlignment)GetValue(HorizontalTextAlignmentProperty); set => SetValue(HorizontalTextAlignmentProperty, value); }
    public Color? TextColor { get => (Color?)GetValue(TextColorProperty); set => SetValue(TextColorProperty, value); }
    public Color? TitleColor { get => (Color?)GetValue(TitleColorProperty); set => SetValue(TitleColorProperty, value); }

    public TechnicalPicker()
    {
        ColumnDefinitions = [new(GridLength.Star), new(GridLength.Auto)];
        Children.Add(_picker);
        Children.Add(_details);
        Grid.SetColumn(_details, 1);
        _picker.SelectedIndexChanged += (_, _) =>
        {
            if (!_syncing && _picker.SelectedItem is Choice choice)
            {
                SelectedItem = choice.Item;
                SelectedIndexChanged?.Invoke(this, EventArgs.Empty);
            }
        };
        _details.Clicked += async (_, _) =>
        {
            if (_showing || _picker.SelectedItem is not Choice choice || TechnicalLabel.FindPage(this) is not { } page) return;
            _showing = true;
            _disclosure = new();
            try { await MessageDetailsPage.ShowAsync(page, "Selected option details", choice.Details, reveal: true, validity: _disclosure.Token); }
            finally { _showing = false; _disclosure.Dispose(); _disclosure = null; }
        };
        Unloaded += (_, _) => { Observe(null); ObserveItems([]); _disclosure?.Cancel(); };
        Loaded += (_, _) => { Observe(ItemsSource as INotifyCollectionChanged); BuildChoices(); };
    }

    private static void ItemsChanged(BindableObject target, object oldValue, object newValue)
    {
        var control = (TechnicalPicker)target;
        control.Observe(newValue as INotifyCollectionChanged);
        control.BuildChoices();
    }
    private void Observe(INotifyCollectionChanged? source)
    {
        if (_observed is not null) _observed.CollectionChanged -= OnCollectionChanged;
        _observed = source;
        if (_observed is not null) _observed.CollectionChanged += OnCollectionChanged;
    }
    private void OnCollectionChanged(object? sender, NotifyCollectionChangedEventArgs args) => BuildChoices();
    private void OnItemChanged(object? sender, PropertyChangedEventArgs args) => BuildChoices();
    private void ObserveItems(IEnumerable<INotifyPropertyChanged> items)
    {
        foreach (var item in _observedItems) item.PropertyChanged -= OnItemChanged;
        _observedItems.Clear();
        foreach (var item in items.Distinct())
        {
            _observedItems.Add(item);
            item.PropertyChanged += OnItemChanged;
        }
    }
    private static void SelectionChanged(BindableObject target, object oldValue, object newValue) => ((TechnicalPicker)target).SelectChoice();
    private static void AppearanceChanged(BindableObject target, object oldValue, object newValue)
    {
        var control = (TechnicalPicker)target;
        control._picker.Title = TechnicalValuePresentation.Summary(control.Title);
        control._picker.FontSize = control.FontSize;
        control._picker.HorizontalTextAlignment = control.HorizontalTextAlignment;
        if (control.TextColor is { } textColor) control._picker.TextColor = textColor;
        if (control.TitleColor is { } titleColor) control._picker.TitleColor = titleColor;
    }

    private void BuildChoices()
    {
        _syncing = true;
        try
        {
            var items = ItemsSource?.Cast<object>().ToArray() ?? [];
            ObserveItems([]);
            var rawLabels = items.Select(item => _reader.Read(item, ItemDisplayBinding)).ToArray();
            var labels = TechnicalValuePresentation.ChoiceLabels(rawLabels);
            _choices = items.Select((item, index) => new Choice(item, labels[index],
                ItemDetailsBinding is null ? rawLabels[index] : _reader.Read(item, ItemDetailsBinding))).ToList();
            _picker.ItemsSource = _choices;
            ObserveItems(items.OfType<INotifyPropertyChanged>());
        }
        finally { _syncing = false; }
        SelectChoice();
    }

    private void SelectChoice()
    {
        _syncing = true;
        try { _picker.SelectedItem = _choices.FirstOrDefault(choice => Equals(choice.Item, SelectedItem)); }
        finally { _syncing = false; }
        RefreshDetails();
    }

    private void RefreshDetails()
    {
        _disclosure?.Cancel();
        var choice = _picker.SelectedItem as Choice;
        var raw = choice?.Details;
        _details.IsVisible = !string.IsNullOrEmpty(raw) &&
            (TechnicalValuePresentation.HasDetails(raw) || ItemDetailsBinding is not null && raw != choice?.Display);
        ToolTipProperties.SetText(_details, _details.IsVisible ? raw ?? string.Empty : string.Empty);
        ToolTipProperties.SetText(_picker, _details.IsVisible ? raw ?? string.Empty : string.Empty);
    }

    private sealed record Choice(object Item, string Display, string Details);

    private sealed class ValueReader : BindableObject
    {
        private static readonly BindableProperty ValueProperty = BindableProperty.Create(
            "Value", typeof(string), typeof(ValueReader), string.Empty);

        public string Read(object item, BindingBase? binding)
        {
            if (binding is null) return item.ToString() ?? string.Empty;
            BindingContext = item;
            try
            {
                // Let MAUI evaluate every BindingBase, including source-generated/typed bindings.
                SetBinding(ValueProperty, binding);
                return (string?)GetValue(ValueProperty) ?? string.Empty;
            }
            finally
            {
                RemoveBinding(ValueProperty);
                ClearValue(ValueProperty);
                BindingContext = null;
            }
        }
    }
}
