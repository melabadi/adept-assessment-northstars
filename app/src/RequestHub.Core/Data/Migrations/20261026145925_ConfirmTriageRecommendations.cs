using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace RequestHub.Core.Data.Migrations
{
    /// <inheritdoc />
    public partial class ConfirmTriageRecommendations : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.AddColumn<string>(
                name: "ConfirmedById",
                table: "Recommendations",
                type: "character varying(80)",
                maxLength: 80,
                nullable: true);
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropColumn(
                name: "ConfirmedById",
                table: "Recommendations");
        }
    }
}
